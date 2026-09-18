"""Discovery, DOI queueing, raw retrieval, and resumable acquisition service."""

from __future__ import annotations

import logging
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
    PaperCreate,
    PaperStage,
    TaskType,
)
from lit_harvest.providers.base import FullTextResult
from lit_harvest.providers.registry import ProviderRegistry
from lit_harvest.services.normalization import NormalizationService
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage, sha256_bytes

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchResult:
    query: str
    discovered: int
    stored: int
    pages: int
    total_results: int | None
    raw_paths: list[str]


@dataclass(slots=True)
class ImportResult:
    queued: int
    duplicates: int
    invalid: list[dict[str, Any]]


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
    ) -> None:
        self.config = config
        self.database = database
        self.storage = storage
        self.providers = providers
        self.normalization = normalization

    def search(
        self,
        query: str,
        *,
        max_results: int,
        start_year: int | None = None,
        end_year: int | None = None,
        export: str | None = None,
    ) -> SearchResult:
        provider = self.providers.get("elsevier")
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
                if self.database.upsert_paper(item):
                    stored += 1
        if export:
            from lit_harvest.services.papers import PaperService

            PaperService(self.database).export(export)
        return SearchResult(
            query=query,
            discovered=discovered,
            stored=stored,
            pages=len(pages),
            total_results=total_results,
            raw_paths=raw_paths,
        )

    def import_dois(self, path: str | Path, *, doi_column: str = "doi") -> ImportResult:
        loaded = load_dois(path, doi_column=doi_column)
        queued = 0
        duplicates = 0
        for item in loaded.valid:
            existing = self.database.get_paper_by_doi(item.doi)
            if existing:
                duplicates += 1
                paper = existing
            else:
                paper = self.database.create_paper(
                    PaperCreate(doi=item.doi, discovery_source="doi_import")
                )
            job = JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=paper.id,
                provider="elsevier",
                service="article_retrieval",
                max_attempts=self.config.scheduler.retry.max_attempts,
                payload={"doi": item.doi},
            )
            before = self.database.count_jobs()
            self.database.create_job(job)
            if self.database.count_jobs() > before:
                queued += 1
        return ImportResult(
            queued=queued,
            duplicates=duplicates,
            invalid=[
                {"raw": item.raw, "row": item.source_row, "reason": item.reason}
                for item in loaded.invalid
            ],
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
        self.database.create_job(
            JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=paper.id,
                provider="elsevier",
                service="article_retrieval",
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
        job = self.database.create_job(
            JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=paper.id,
                provider="elsevier",
                service="article_retrieval",
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

        provider = self.providers.get(job.provider or "elsevier")
        if not hasattr(provider, "fetch_fulltext"):
            raise TypeError(f"Provider does not support full-text retrieval: {provider.name}")
        result: FullTextResult = provider.fetch_fulltext(doi)
        raw_path = self.storage.write_raw(
            doi,
            f"{result.provider}_{result.format}.xml"
            if result.format == "xml"
            else f"{result.provider}_{result.format}",
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
            download = self.database.latest_download(paper.id)
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
                self.normalization.normalize(
                    content=raw_path.read_bytes(),
                    doi=doi,
                    paper_id=paper.id,
                    source_path=str(raw_path),
                    http_status=download.get("http_status"),
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001 - batch parser isolates per paper
                failed += 1
                self.database.add_paper_extra(paper.id, {"last_parse_error": str(exc)})
        return {"processed": processed, "failed": failed, "skipped": skipped}

    def _existing_success(self, paper_id: str) -> dict[str, Any] | None:
        download = self.database.latest_download(paper_id)
        if not download or download.get("status") != DownloadStatus.SUCCESS.value:
            return None
        raw_path = download.get("raw_path")
        if not raw_path or not Path(str(raw_path)).exists():
            return None
        return download
