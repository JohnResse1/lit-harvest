"""Discovery, DOI queueing, raw retrieval, and resumable acquisition service."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lit_harvest.config import AppConfig
from lit_harvest.input.doi_loader import load_dois, load_single_doi
from lit_harvest.models import (
    DownloadStatus,
    Job,
    JobCreate,
    JobStatus,
    Paper,
    PaperCreate,
    PaperIdentifiers,
    PaperStage,
    TaskType,
)
from lit_harvest.providers.base import FullTextResult, ProviderUnavailableError
from lit_harvest.providers.oa import OpenAccessFetcher
from lit_harvest.providers.registry import ProviderRegistry
from lit_harvest.services.cache import CacheService
from lit_harvest.services.normalization import NormalizationService
from lit_harvest.services.resolver import Resolver
from lit_harvest.services.search_sessions import SearchCandidate, SearchSessionStore
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage, sha256_bytes

logger = logging.getLogger(__name__)


def _clean_error_message(exc: Exception) -> str:
    """Never surface raw provider payloads in results shown to users."""
    from lit_harvest.providers.base import ProviderError, user_message

    if isinstance(exc, ProviderError):
        return user_message(exc)
    message = str(exc)
    if message.startswith("<") or len(message) > 300:
        return "The request failed."
    return message


@dataclass(slots=True)
class SearchResult:
    query: str
    discovered: int
    stored: int
    pages: int
    total_results: int | None
    raw_paths: list[str]
    session_id: str | None = None


@dataclass(slots=True)
class ImportResult:
    queued: int
    duplicates: int
    invalid: list[dict[str, Any]]
    paper_ids: list[str]
    queued_paper_ids: list[str]


@dataclass(slots=True)
class FetchResult:
    paper_id: str
    doi: str
    raw_path: str
    normalized_path: str | None
    reused: bool
    document: dict[str, Any] | None = None


class AcquisitionService:
    task_type = TaskType.FETCH_FULLTEXT

    def __init__(
        self,
        *,
        config: AppConfig,
        database: Database,
        storage: DocumentStorage,
        providers: ProviderRegistry,
        normalization: NormalizationService,
        cache: CacheService | None = None,
        oa_fetcher: OpenAccessFetcher | None = None,
    ) -> None:
        self.config = config
        self.database = database
        self.storage = storage
        self.providers = providers
        self.normalization = normalization
        self.cache = cache
        self.oa_fetcher = oa_fetcher or OpenAccessFetcher()
        self.resolver = Resolver(providers)
        self.search_sessions = SearchSessionStore(database)

    def search(
        self,
        query: str,
        *,
        max_results: int,
        start_year: int | None = None,
        end_year: int | None = None,
        export: str | None = None,
        provider_name: str | None = None,
    ) -> SearchResult:
        provider: Any | None
        if provider_name:
            selected = self.providers.get(provider_name)
            if not getattr(selected, "supports_search", False):
                raise ProviderUnavailableError(
                    f"{provider_name} does not support literature search."
                )
            provider = selected
        else:
            provider = self.providers.first_with_capability("supports_search")
        if provider is None:
            raise ProviderUnavailableError(
                "No configured provider supports literature search. "
                "Configure a discovery provider such as Elsevier Scopus."
            )
        pages = provider.search(
            query,
            max_results=max_results,
            start_year=start_year,
            end_year=end_year,
        )
        discovered = 0
        stored = 0
        raw_paths: list[str] = []
        total_results = None
        candidates: list[SearchCandidate] = []
        for index, page in enumerate(pages, start=1):
            raw_path = self.storage.write_raw(
                f"search/{datetime.now(UTC).strftime('%Y%m%d')}",
                f"scopus_{index}_{sha256_bytes(page.raw)[:12]}.json",
                page.raw,
            )
            raw_paths.append(str(raw_path))
            total_results = page.total_results if page.total_results is not None else total_results
            for item in page.papers:
                discovered += 1
                paper = self.database.upsert_paper(item)
                if paper is not None:
                    stored += 1
                # Search payloads already carry OA details; seeding the resolver
                # avoids a second lookup (and its pacing delay) at fetch time.
                self._prime_oa_from_search(item)
                candidates.append(
                    self._candidate_from_paper(item, paper_id=paper.id if paper else None)
                )
        if export:
            from lit_harvest.services.papers import PaperService

            PaperService(self.database).export(export)
        session = self.search_sessions.create(
            query=query,
            max_results=max_results,
            total_results=total_results,
            raw_paths=raw_paths,
            candidates=candidates,
        )
        return SearchResult(
            query=query,
            discovered=discovered,
            stored=stored,
            pages=len(pages),
            total_results=total_results,
            raw_paths=raw_paths,
            session_id=session.session_id,
        )

    def _prime_oa_from_search(self, paper: PaperCreate) -> None:
        if not paper.doi:
            return
        oa = (paper.extra or {}).get("open_access")
        if not isinstance(oa, dict):
            return
        self.resolver.prime_oa_cache(
            paper.doi,
            {
                "is_oa": oa.get("is_oa"),
                "oa_status": oa.get("oa_status") or oa.get("type"),
                "oa_url": oa.get("oa_url"),
                "pdf_url": oa.get("pdf_url"),
                "license": oa.get("license"),
                "version": oa.get("version"),
                "source": paper.discovery_source,
            },
        )

    @staticmethod
    def _candidate_from_paper(paper: PaperCreate, *, paper_id: str | None) -> SearchCandidate:
        extra = paper.extra or {}
        authors = None
        author_field = extra.get("author")
        if isinstance(author_field, dict):
            names = author_field.get("author")
            if isinstance(names, list):
                authors = (
                    "; ".join(
                        str(item.get("authname"))
                        for item in names
                        if isinstance(item, dict) and item.get("authname")
                    )
                    or None
                )
        elif isinstance(author_field, list):
            authors = "; ".join(str(item) for item in author_field) or None

        # Scopus Search STANDARD exposes only dc:creator (the first author),
        # so fall back to it when no full author list is available.
        if not authors:
            creator = extra.get("creator")
            if isinstance(creator, str) and creator.strip():
                authors = creator.strip()

        affiliation = extra.get("affiliation_text")
        if not affiliation:
            raw_affiliation = extra.get("affiliation")
            if isinstance(raw_affiliation, list):
                affiliation = (
                    "; ".join(
                        str(item.get("affilname"))
                        for item in raw_affiliation
                        if isinstance(item, dict) and item.get("affilname")
                    )
                    or None
                )

        open_access: bool | None = None
        raw_oa = extra.get("openaccessFlag")
        if raw_oa is None:
            raw_oa = extra.get("openaccess")
        if raw_oa is not None:
            open_access = str(raw_oa).lower() in {"1", "true", "yes"}

        free_to_read = None
        raw_free = extra.get("freetoreadLabel")
        if isinstance(raw_free, dict):
            values = raw_free.get("value")
            if isinstance(values, list):
                free_to_read = (
                    "; ".join(
                        str(item.get("$"))
                        for item in values
                        if isinstance(item, dict) and item.get("$")
                    )
                    or None
                )
        elif isinstance(raw_free, str):
            free_to_read = raw_free

        citation_count = extra.get("citation_count")
        return SearchCandidate(
            candidate_id=uuid.uuid4().hex,
            paper_id=paper_id,
            doi=paper.doi,
            title=paper.title,
            journal=paper.journal,
            year=paper.publication_year,
            authors=authors,
            affiliation=affiliation,
            document_type=paper.document_type,
            citation_count=int(citation_count) if isinstance(citation_count, int) else None,
            open_access=open_access,
            free_to_read=free_to_read,
            issn=str(extra.get("prism:issn") or "") or None,
            volume=str(extra.get("prism:volume") or "") or None,
            issue=str(extra.get("prism:issueIdentifier") or "") or None,
            pages=str(extra.get("prism:pageRange") or "") or None,
            cover_date=str(extra.get("prism:coverDate") or "") or None,
            scopus_id=paper.identifiers.scopus_id,
            eid=paper.identifiers.eid,
            scopus_url=str(extra.get("prism:url") or "") or None,
        )

    def fetch_selected(self, session_id: str, *, download_pdf: bool = False) -> dict[str, Any]:
        """Download only the candidates the user ticked, then return a summary."""
        selected = self.search_sessions.selected(session_id)
        if not selected:
            raise ValueError("No papers were selected.")
        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for candidate in selected:
            doi = candidate.doi
            if not doi:
                failed += 1
                results.append({"doi": None, "status": "skipped", "reason": "no DOI"})
                continue
            try:
                fetched = self.fetch_now(doi)
                entry: dict[str, Any] = {
                    "doi": doi,
                    "status": "ok",
                    "paper_id": fetched.paper_id,
                    "reused": fetched.reused,
                }
                if download_pdf:
                    try:
                        entry["pdf"] = self.fetch_pdf(fetched.paper_id)
                    except Exception as exc:  # noqa: BLE001 - XML success stands
                        entry["pdf_error"] = getattr(exc, "code", "pdf_failed")
                succeeded += 1
                results.append(entry)
            except Exception as exc:  # noqa: BLE001 - per-paper isolation
                failed += 1
                results.append(
                    {
                        "doi": doi,
                        "status": "failed",
                        "error": getattr(exc, "code", "fetch_failed"),
                        "message": _clean_error_message(exc),
                    }
                )
        return {
            "session_id": session_id,
            "requested": len(selected),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    def import_dois(self, path: str | Path, *, doi_column: str = "doi") -> ImportResult:
        loaded = load_dois(path, doi_column=doi_column)
        queued = 0
        duplicates = 0
        paper_ids: list[str] = []
        queued_paper_ids: list[str] = []
        for item in loaded.valid:
            existing = self.database.get_paper_by_doi(item.doi)
            if existing:
                duplicates += 1
                paper = existing
            else:
                paper = self.database.create_paper(
                    PaperCreate(doi=item.doi, discovery_source="doi_import")
                )
            paper_ids.append(paper.id)
            route = self.resolver.route_for_job(item.doi)
            job = JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=paper.id,
                provider=route.provider if route else None,
                service=route.service if route else None,
                max_attempts=self.config.scheduler.retry.max_attempts,
                payload={"doi": item.doi},
            )
            before = self.database.count_jobs()
            self.database.create_job(job)
            if self.database.count_jobs() > before:
                queued += 1
                queued_paper_ids.append(paper.id)
        return ImportResult(
            queued=queued,
            duplicates=duplicates,
            invalid=[
                {"raw": item.raw, "row": item.source_row, "reason": item.reason}
                for item in loaded.invalid
            ],
            paper_ids=paper_ids,
            queued_paper_ids=queued_paper_ids,
        )

    def queue_doi(self, doi: str) -> tuple[str, bool]:
        normalized = load_single_doi(doi)
        paper = self.database.get_paper_by_doi(normalized)
        created_paper = paper is None
        if paper is None:
            paper = self.database.create_paper(
                PaperCreate(doi=normalized, discovery_source="single_doi")
            )
        before = self.database.count_jobs()
        route = self.resolver.best(normalized)
        self.database.create_job(
            JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=paper.id,
                provider=route.provider if route else None,
                service=route.service if route else None,
                max_attempts=self.config.scheduler.retry.max_attempts,
                payload={"doi": normalized},
            )
        )
        return paper.id, created_paper and self.database.count_jobs() > before

    def fetch_now(self, doi: str) -> FetchResult:
        normalized = load_single_doi(doi)
        paper = self.database.get_paper_by_doi(normalized)
        if paper is None:
            paper = self.database.create_paper(
                PaperCreate(doi=normalized, discovery_source="single_doi")
            )
        route = self.resolver.route_for_job(normalized)
        job = self.database.create_job(
            JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=paper.id,
                provider=route.provider if route else None,
                service=route.service if route else None,
                max_attempts=self.config.scheduler.retry.max_attempts,
                payload={"doi": normalized},
            )
        )
        try:
            result = self.fetch_job(job)
        except Exception as exc:
            self.database.update_job_status(
                job.id,
                JobStatus.FAILED,
                error_code=getattr(exc, "code", "fetch_failed"),
                error_message=str(exc),
            )
            raise
        self.database.update_job_status(job.id, JobStatus.SUCCESS)
        return result

    def fetch_pdf(self, paper_id: str) -> dict[str, Any]:
        paper = self.database.get_paper(paper_id)
        if paper is None:
            raise KeyError(f"Paper not found: {paper_id}")
        if not paper.doi:
            raise ValueError("PDF download requires a DOI")
        provider = self.providers.first_with_capability("supports_pdf")
        if provider is None or not hasattr(provider, "fetch_pdf"):
            raise ProviderUnavailableError("No configured provider can supply publisher PDFs.")
        existing = self.storage.paper_dir(paper.doi) / "raw" / "elsevier_pdf.pdf"
        if existing.exists():
            self.database.add_paper_extra(
                paper.id,
                {"pdf_path": str(existing), "pdf_reused": True},
            )
            return {
                "paper_id": paper.id,
                "doi": paper.doi,
                "pdf_path": str(existing),
                "reused": True,
            }
        result: FullTextResult = provider.fetch_pdf(paper.doi)
        path = self.storage.write_raw(paper.doi, "elsevier_pdf.pdf", result.content)
        self.database.record_download(
            paper_id=paper.id,
            provider=result.provider,
            service=result.service,
            credential_id=result.credential.id if result.credential else None,
            status=DownloadStatus.SUCCESS.value,
            format="pdf",
            raw_path=str(path),
            checksum=sha256_bytes(result.content),
            http_status=result.http_status,
        )
        self.database.add_paper_extra(
            paper.id,
            {
                "pdf_path": str(path),
                "pdf_checksum": sha256_bytes(result.content),
                "pdf_reused": False,
            },
        )
        self.storage.write_state(
            paper.doi,
            {**self.storage.read_state(paper.doi), "pdf_path": str(path)},
        )
        raw_download = self._existing_success(paper.id)
        if raw_download and raw_download.get("raw_path"):
            raw_path = Path(str(raw_download["raw_path"]))
            if raw_path.exists():
                self.normalization.normalize(
                    content=raw_path.read_bytes(),
                    doi=paper.doi,
                    paper_id=paper.id,
                    source_path=str(raw_path),
                    http_status=raw_download.get("http_status"),
                    provider=str(raw_download.get("provider") or "") or None,
                    service=str(raw_download.get("service") or "") or None,
                    format=str(raw_download.get("format") or "xml"),
                    pdf_path=str(path),
                )
        return {"paper_id": paper.id, "doi": paper.doi, "pdf_path": str(path), "reused": False}

    def _try_open_access(self, paper: Paper, doi: str, job: Job) -> FetchResult | None:
        """Download a free copy when one exists; otherwise return None.

        Failure here is never fatal: the caller falls back to the publisher.
        """
        # OA-first routing is only meaningful when at least one OA-capable
        # provider (OpenAlex, Unpaywall, Europe PMC, ...) is enabled.
        if not any(
            getattr(provider, "supports_oa_lookup", False)
            for provider in self.providers.with_capability("supports_oa_lookup")
        ):
            return None
        try:
            oa = self.resolver.oa_lookup(doi)
        except Exception as exc:  # noqa: BLE001 - lookup must never block retrieval
            logger.debug("OA lookup failed for %s: %s", doi, exc)
            return None
        if not oa.downloadable or not oa.pdf_url:
            return None
        try:
            payload = self.oa_fetcher.fetch(oa.pdf_url)
        except Exception as exc:  # noqa: BLE001 - fall back to the publisher
            logger.info("OA download failed for %s, falling back to publisher: %s", doi, exc)
            self.database.record_event(
                provider=oa.source or "openaccess",
                service="oa_download",
                paper_id=paper.id,
                job_id=job.id,
                event_type="oa_fallback",
                level="warning",
                message=str(exc),
            )
            return None

        raw_path = self.storage.write_raw(
            doi, f"openaccess.{payload['format']}", payload["content"]
        )
        checksum = sha256_bytes(payload["content"])
        credential_id = job.credential_id
        self.database.record_download(
            paper_id=paper.id,
            provider=oa.source or "openaccess",
            service="oa_download",
            credential_id=credential_id,
            status=DownloadStatus.SUCCESS.value,
            format=payload["format"],
            raw_path=str(raw_path),
            checksum=checksum,
            http_status=payload["http_status"],
        )
        self.database.add_paper_extra(
            paper.id,
            {
                "oa_status": oa.oa_status,
                "oa_license": oa.license,
                "oa_url": payload["url"],
                "free_access": True,
            },
        )
        self.storage.write_state(
            doi,
            {
                "stage": PaperStage.DOWNLOADED.value,
                "doi": doi,
                "raw_path": str(raw_path),
                "provider": oa.source or "openaccess",
                "service": "oa_download",
                "http_status": payload["http_status"],
                "checksum": checksum,
                "free_access": True,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        self.database.set_paper_stage(paper.id, PaperStage.DOWNLOADED)

        # Normalize whatever deterministic parser can handle the payload
        # (JATS/Elsevier XML, HTML, or a PDF text layer). OCR is never run.
        normalized_path: str | None = None
        document: dict[str, Any] | None = None
        if self.normalization.can_normalize(
            format=payload["format"], content=payload["content"]
        ):
            try:
                normalized = self.normalization.normalize(
                    content=payload["content"],
                    doi=doi,
                    paper_id=paper.id,
                    source_path=str(raw_path),
                    credential_label=None,
                    http_status=payload["http_status"],
                    provider=oa.source or "openaccess",
                    service="oa_download",
                    format=payload["format"],
                )
                normalized_path = str(normalized["path"])
                document = normalized["document"]
            except Exception as exc:  # noqa: BLE001 - raw file is still valuable
                logger.info("OA document for %s could not be normalized: %s", doi, exc)
        return FetchResult(
            paper_id=paper.id,
            doi=doi,
            raw_path=str(raw_path),
            normalized_path=normalized_path,
            reused=False,
            document=document,
        )

    def _provider_for_fetch(self, job: Job, doi: str) -> Any:
        """Pick the provider for a job, honouring an explicitly pinned route."""
        if job.provider:
            provider = self.providers.get(job.provider)
            if not getattr(provider, "supports_fulltext", False):
                raise ProviderUnavailableError(
                    f"Provider {provider.name} cannot retrieve full text."
                )
            return provider
        route = self.resolver.route_for_job(doi)
        if route is None:
            raise ProviderUnavailableError(
                "No configured provider can retrieve full text for this DOI."
            )
        return self.providers.get(route.provider)

    def enrich_metadata(self, *, limit: int = 100, only_incomplete: bool = True) -> dict[str, Any]:
        """Fill missing bibliographic fields using an open metadata provider.

        OpenAlex needs no credentials, so this works for every user. It fixes
        records imported by DOI alone, which otherwise show up without a title,
        authors, or abstract.
        """
        provider = None
        for candidate in self.providers.with_capability("supports_metadata"):
            if candidate.name != "elsevier" and hasattr(candidate, "fetch_metadata"):
                provider = candidate
                break
        if provider is None:
            raise ProviderUnavailableError(
                "No metadata provider is available. Enable OpenAlex in config.yaml."
            )

        enriched = skipped = failed = 0
        results: list[dict[str, Any]] = []
        for paper in self.database.list_papers(limit=limit):
            if not paper.doi:
                skipped += 1
                continue
            if only_incomplete and paper.title:
                skipped += 1
                continue
            try:
                payload = provider.fetch_metadata(paper.doi)
            except Exception as exc:  # noqa: BLE001 - per-paper isolation
                failed += 1
                results.append(
                    {"doi": paper.doi, "status": "failed", "message": _clean_error_message(exc)}
                )
                continue
            if not payload:
                skipped += 1
                continue
            update = PaperCreate(
                doi=payload.get("doi") or paper.doi,
                title=payload.get("title"),
                journal=payload.get("journal"),
                publication_year=payload.get("publication_year"),
                publisher=payload.get("publisher"),
                document_type=payload.get("document_type"),
                identifiers=PaperIdentifiers.model_validate(payload.get("identifiers") or {}),
                extra=payload.get("extra") or {},
            )
            self.database.update_paper_metadata(paper.id, update)
            enriched += 1
            results.append({"doi": paper.doi, "status": "ok", "title": update.title})
        return {
            "enriched": enriched,
            "skipped": skipped,
            "failed": failed,
            "results": results,
        }

    def rebuild_missing(
        self,
        *,
        limit: int = 100,
        download_pdf: bool = False,
        on_progress: Any | None = None,
    ) -> dict[str, Any]:
        """Re-fetch raw full text for papers whose cache was deleted.

        This is the counterpart to `cleanup --raw`: metadata and normalized
        output survive, and the original documents can be restored on demand.
        """
        if self.cache is None:
            raise RuntimeError("Cache service is not available")
        targets = self.cache.missing_raw(limit=limit)
        results: list[dict[str, Any]] = []
        succeeded = failed = 0
        for index, target in enumerate(targets, start=1):
            try:
                fetched = self.fetch_now(target.doi)
                entry: dict[str, Any] = {
                    "doi": target.doi,
                    "status": "ok",
                    "raw_path": fetched.raw_path,
                }
                if download_pdf:
                    try:
                        entry["pdf"] = self.fetch_pdf(fetched.paper_id)
                    except Exception as exc:  # noqa: BLE001 - XML success stands
                        entry["pdf_error"] = _clean_error_message(exc)
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 - per-paper isolation
                failed += 1
                entry = {
                    "doi": target.doi,
                    "status": "failed",
                    "message": _clean_error_message(exc),
                }
            results.append(entry)
            if on_progress is not None:
                on_progress(index, len(targets), entry)
        return {
            "requested": len(targets),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    def pdf_enabled(self, override: bool | None = None) -> bool:
        if override is not None:
            return override
        return self.config.providers.elsevier.download_pdf

    def fetch_job(self, job: Job) -> FetchResult:
        if job.paper_id is None:
            raise ValueError("Fetch job requires paper_id")
        paper = self.database.get_paper(job.paper_id)
        if paper is None:
            raise KeyError(f"Paper not found: {job.paper_id}")
        doi = str(job.payload.get("doi") or paper.doi or "")
        if not doi:
            raise ValueError("Fetch job requires a DOI payload")
        existing = self._existing_success(paper.id)
        if existing:
            normalized_path = paper.extra.get("normalized_path")
            return FetchResult(
                paper_id=paper.id,
                doi=doi,
                raw_path=str(existing["raw_path"]),
                normalized_path=normalized_path,
                reused=True,
                document=paper.extra.get("normalized"),
            )

        # Prefer a free open-access copy: it consumes no institutional quota and
        # keeps ordinary reading invisible to publisher usage monitoring.
        oa_attempt = self._try_open_access(paper, doi, job)
        if oa_attempt is not None:
            return oa_attempt

        provider = self._provider_for_fetch(job, doi)
        result: FullTextResult = provider.fetch_fulltext(doi)
        suffix = "xml" if result.format == "xml" else result.format
        raw_path = self.storage.write_raw(
            doi,
            f"{result.provider}_{result.format}.{suffix}",
            result.content,
        )
        checksum = sha256_bytes(result.content)
        self.database.record_download(
            paper_id=paper.id,
            provider=result.provider,
            service=result.service,
            credential_id=result.credential.id if result.credential else None,
            status=DownloadStatus.SUCCESS.value,
            format=result.format,
            raw_path=str(raw_path),
            checksum=checksum,
            http_status=result.http_status,
        )
        self.storage.write_state(
            doi,
            {
                "stage": PaperStage.DOWNLOADED.value,
                "doi": doi,
                "raw_path": str(raw_path),
                "provider": result.provider,
                "service": result.service,
                "credential_label": result.credential.name if result.credential else None,
                "http_status": result.http_status,
                "checksum": checksum,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        self.database.set_paper_stage(paper.id, PaperStage.DOWNLOADED)
        try:
            normalized = self.normalization.normalize(
                content=result.content,
                doi=doi,
                paper_id=paper.id,
                source_path=str(raw_path),
                credential_label=result.credential.name if result.credential else None,
                http_status=result.http_status,
                provider=result.provider,
                service=result.service,
                format=result.format,
            )
        except Exception as exc:
            self.database.record_event(
                provider=result.provider,
                service=result.service,
                paper_id=paper.id,
                job_id=job.id,
                event_type="parse_error",
                level="error",
                message=str(exc),
            )
            raise
        return FetchResult(
            paper_id=paper.id,
            doi=doi,
            raw_path=str(raw_path),
            normalized_path=str(normalized["path"]),
            reused=False,
            document=normalized["document"],
        )

    def handle_job(self, job: Job) -> dict[str, Any]:
        result = self.fetch_job(job)
        return {
            "paper_id": result.paper_id,
            "doi": result.doi,
            "raw_path": result.raw_path,
            "normalized_path": result.normalized_path,
            "reused": result.reused,
        }

    def parse_pending(self, *, limit: int = 1000, force: bool = False) -> dict[str, int]:
        processed = 0
        failed = 0
        skipped = 0
        for paper in self.database.list_papers(limit=limit):
            if paper.extra.get("normalized_path") and not force:
                skipped += 1
                continue
            download = self._existing_success(paper.id)
            if download is None and not force:
                skipped += 1
                continue
            if download is None:
                candidates = self.database.list_downloads(paper.id)
                download = next(
                    (
                        item
                        for item in reversed(candidates)
                        if item.get("raw_path") and str(item["raw_path"]).lower().endswith(".xml")
                    ),
                    None,
                )
            if not download or not download.get("raw_path"):
                skipped += 1
                continue
            raw_path = Path(str(download["raw_path"]))
            if not raw_path.exists():
                failed += 1
                self.database.add_paper_extra(
                    paper.id, {"last_parse_error": f"Raw file missing: {raw_path}"}
                )
                continue
            doi = paper.doi or str(download.get("doi") or "")
            try:
                pdf_path = paper.extra.get("pdf_path")
                self.normalization.normalize(
                    content=raw_path.read_bytes(),
                    doi=doi,
                    paper_id=paper.id,
                    source_path=str(raw_path),
                    http_status=download.get("http_status"),
                    provider=str(download.get("provider") or "") or None,
                    service=str(download.get("service") or "") or None,
                    format=str(download.get("format") or "xml"),
                    pdf_path=str(pdf_path) if pdf_path else None,
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001 - batch parser isolates per paper
                failed += 1
                self.database.add_paper_extra(paper.id, {"last_parse_error": str(exc)})
        return {"processed": processed, "failed": failed, "skipped": skipped}

    def _existing_success(self, paper_id: str) -> dict[str, Any] | None:
        for download in reversed(self.database.list_downloads(paper_id)):
            if download.get("status") != DownloadStatus.SUCCESS.value:
                continue
            if download.get("format") != "xml":
                continue
            raw_path = download.get("raw_path")
            if not raw_path or not Path(str(raw_path)).exists():
                continue
            return download
        return None
