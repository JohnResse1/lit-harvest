"""Europe PMC provider: key-free search plus open-access JATS full text.

Europe PMC is funded as a public resource and needs no API key. Two things make
it valuable here:

* **Discovery** across the life-science literature with no credentials.
* **Free structured full text**: when a record has a PMCID, the article is
  available as JATS XML. That is a *structured* document (better than a PDF) and
  it is open access, so it costs no institutional subscription quota.

The provider therefore advertises both ``supports_fulltext`` and
``supports_oa_lookup``. Full text is only ever returned for records that Europe
PMC actually hosts; everything else falls through to the normal publisher route.
"""

from __future__ import annotations

import json
from typing import Any

from lit_harvest.models import HealthStatus
from lit_harvest.policy import PolicyService
from lit_harvest.providers.base import (
    FullTextResult,
    HealthCheckResult,
    NotFoundError,
    ProviderError,
    SearchPage,
)
from lit_harvest.providers.europepmc.parser import (
    parse_europepmc_record,
    parse_search_response,
)
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.storage.database import Database


class EuropePmcProvider:
    name = "europepmc"
    display_name = "Europe PMC"

    supports_search = True
    # Structured JATS XML for open-access records.
    supports_fulltext = True
    supports_pdf = False
    supports_metadata = True
    supports_oa_lookup = True
    requires_credential = False

    search_service = "europepmc_search"
    metadata_service = "europepmc_search"
    fulltext_service = "europepmc_fulltext"
    oa_service = "europepmc_oa_fulltext"

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    MAX_PAGE_SIZE = 100

    def __init__(
        self,
        *,
        database: Database,
        client: JsonHttpClient | None = None,
        contact_email: str | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
        policy: PolicyService | None = None,
    ) -> None:
        self.database = database
        self.contact_email = contact_email
        self.policy = policy
        self.client = client or JsonHttpClient(
            base_url=self.BASE_URL,
            provider=self.name,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            policy=policy,
        )
        # PMCID cache so an OA lookup and a later retrieval share one search.
        self._pmcid_cache: dict[str, str | None] = {}

    # ------------------------------------------------------------ healthcheck

    def healthcheck(
        self, service: str | None = None, *, network: bool = True
    ) -> list[HealthCheckResult]:
        services = [service] if service else [self.search_service, self.fulltext_service]
        if not network:
            return [
                HealthCheckResult(self.name, item, HealthStatus.HEALTHY, "No credentials required")
                for item in services
            ]
        try:
            self.search("battery", max_results=1)
        except ProviderError as exc:
            return [
                HealthCheckResult(
                    self.name,
                    item,
                    HealthStatus.UNHEALTHY,
                    exc.message,
                    {"status_code": exc.status_code, "error_code": exc.code},
                )
                for item in services
            ]
        return [
            HealthCheckResult(self.name, item, HealthStatus.HEALTHY, "Reachable")
            for item in services
        ]

    # ----------------------------------------------------------------- search

    def search(
        self,
        query: str,
        *,
        max_results: int,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[SearchPage]:
        if max_results < 1:
            raise ValueError("max_results must be >= 1")
        pages: list[SearchPage] = []
        retrieved = 0
        total: int | None = None
        cursor = "*"

        while retrieved < max_results:
            page_size = min(self.MAX_PAGE_SIZE, max_results - retrieved)
            params: dict[str, Any] = {
                "query": self._query(query, start_year, end_year),
                "format": "json",
                "resultType": "core",
                "pageSize": page_size,
                "cursorMark": cursor,
            }
            response = self.client.request(
                "/search", params=params, service=self.search_service
            )
            payload = self._json(response)
            papers, info = parse_search_response(payload)
            total = info.get("total_results", total)
            next_cursor = info.get("next_cursor")
            pages.append(
                SearchPage(
                    papers=papers,
                    total_results=total,
                    start_index=retrieved,
                    items_per_page=page_size,
                    current_cursor=cursor,
                    next_cursor=str(next_cursor) if next_cursor else None,
                    raw=response.content,
                )
            )
            retrieved += len(papers)
            if not papers or len(papers) < page_size or not next_cursor:
                break
            if total is not None and retrieved >= total:
                break
            cursor = str(next_cursor)
        return pages

    @staticmethod
    def _query(query: str, start_year: int | None, end_year: int | None) -> str:
        parts = [f"({query})"]
        if start_year:
            parts.append(f"FIRST_PDATE:[{start_year}-01-01 TO 9999-12-31]")
        if end_year:
            parts.append(f"(FIRST_PDATE:[0001-01-01 TO {end_year}-12-31])")
        return " AND ".join(parts) if len(parts) > 1 else query

    # --------------------------------------------------------------- metadata

    def fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        record = self._search_record_for_doi(doi)
        if not record:
            return None
        return parse_europepmc_record(record).model_dump(mode="json")

    # --------------------------------------------------------------- fulltext

    def fetch_oa_location(self, doi: str) -> dict[str, Any] | None:
        """Return the JATS full-text URL when Europe PMC hosts the article.

        This is a *free* structured document, so routing to it avoids the
        institutional subscription quota entirely.
        """
        record = self._search_record_for_doi(doi)
        if not record:
            return None
        pmcid = record.get("pmcid")
        if not pmcid or not isinstance(pmcid, str):
            return None
        url = self.fulltext_url(pmcid)
        return {
            "doi": record.get("doi"),
            "is_oa": True,
            "downloadable": True,
            "oa_status": "open",
            # A structured JATS document, not a PDF; reported so the resolver
            # labels the candidate honestly.
            "file_format": "xml",
            "pdf_url": url,
            # `pmcid` already carries the PMC prefix (e.g. PMC7014107).
            "landing_url": f"https://europepmc.org/article/PMC/{pmcid.removeprefix('PMC')}",
            "license": None,
            "version": "publishedVersion",
            "source": self.name,
        }

    def fulltext_url(self, pmcid: str) -> str:
        return f"{self.BASE_URL}/{pmcid}/fullTextXML"

    def fetch_fulltext(self, doi: str) -> FullTextResult:
        record = self._search_record_for_doi(doi)
        if not record:
            raise NotFoundError("Europe PMC has no record for this DOI.")
        pmcid = record.get("pmcid")
        if not pmcid or not isinstance(pmcid, str):
            raise NotFoundError("Europe PMC does not host open-access full text for this DOI.")
        response = self.client.request(
            f"/{pmcid}/fullTextXML",
            headers={"Accept": "application/xml"},
            service=self.fulltext_service,
            paper_doi=doi,
        )
        return FullTextResult(
            doi=doi,
            content=response.content,
            content_type=response.headers.get("content-type", "application/xml"),
            format="xml",
            http_status=response.status_code,
            url=response.url,
            provider=self.name,
            service=self.fulltext_service,
            credential=None,
            headers=response.headers,
        )

    # ---------------------------------------------------------------- helpers

    def _search_record_for_doi(self, doi: str) -> dict[str, Any] | None:
        normalized = _strip_doi(doi)
        if not normalized:
            return None
        cache_key = normalized.lower()
        if cache_key in self._pmcid_cache:
            pmcid = self._pmcid_cache[cache_key]
            return {"pmcid": pmcid, "doi": normalized} if pmcid else None

        response = self.client.request(
            "/search",
            params={
                "query": f'DOI:"{normalized}"',
                "format": "json",
                "resultType": "core",
                "pageSize": 1,
            },
            service=self.metadata_service,
            paper_doi=normalized,
        )
        payload = self._json(response)
        result_list = payload.get("resultList")
        result_list = result_list if isinstance(result_list, dict) else {}
        results = result_list.get("result")
        record = results[0] if isinstance(results, list) and results else None
        if not isinstance(record, dict):
            self._pmcid_cache[cache_key] = None
            return None
        pmcid = record.get("pmcid")
        self._pmcid_cache[cache_key] = pmcid if isinstance(pmcid, str) else None
        return record

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Europe PMC returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Europe PMC returned an unexpected payload")
        return payload


def _strip_doi(value: str) -> str:
    text = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :]
    return text
