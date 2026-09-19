"""OpenAlex provider: key-free, cross-publisher discovery and metadata.

OpenAlex indexes works from essentially every publisher and publishes the data
under CC0. It is metadata only - no full text - so it complements the publisher
providers rather than competing with them:

  * discovery and metadata enrichment need no credentials
  * publisher providers remain the only route to entitled full text
"""

from __future__ import annotations

import json
from typing import Any

from lit_harvest.policy import PolicyService
from lit_harvest.providers.base import (
    HealthCheckResult,
    ProviderError,
    SearchPage,
)
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.openalex.parser import parse_search_response, strip_doi
from lit_harvest.storage.database import Database


class OpenAlexProvider:
    name = "openalex"
    display_name = "OpenAlex"

    # Metadata-only provider: it can search and enrich, but never serves files.
    supports_search = True
    supports_fulltext = False
    supports_pdf = False
    supports_metadata = True

    search_service = "works_search"
    metadata_service = "works_lookup"

    BASE_URL = "https://api.openalex.org"
    # OpenAlex allows up to 200 per page.
    MAX_PAGE_SIZE = 200

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

    # ------------------------------------------------------------ healthcheck

    def healthcheck(
        self, service: str | None = None, *, network: bool = True
    ) -> list[HealthCheckResult]:
        services = [service] if service else [self.search_service, self.metadata_service]
        results: list[HealthCheckResult] = []
        if not network:
            for item in services:
                results.append(
                    HealthCheckResult(self.name, item, self._health_ok(), "No credentials required")
                )
            return results
        try:
            self.search("battery", max_results=1)
            for item in services:
                results.append(HealthCheckResult(self.name, item, self._health_ok(), "Reachable"))
        except ProviderError as exc:
            for item in services:
                results.append(
                    HealthCheckResult(
                        self.name,
                        item,
                        self._health_unhealthy(),
                        exc.message,
                        {"status_code": exc.status_code, "error_code": exc.code},
                    )
                )
        return results

    @staticmethod
    def _health_ok() -> Any:
        from lit_harvest.models import HealthStatus

        return HealthStatus.HEALTHY

    @staticmethod
    def _health_unhealthy() -> Any:
        from lit_harvest.models import HealthStatus

        return HealthStatus.UNHEALTHY

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
        page_number = 1

        while retrieved < max_results:
            per_page = min(self.MAX_PAGE_SIZE, max_results - retrieved)
            params: dict[str, Any] = {
                "search": query,
                "per-page": per_page,
                "page": page_number,
            }
            filters = self._year_filter(start_year, end_year)
            if filters:
                params["filter"] = filters
            mailto = self._mailto()
            if mailto:
                params["mailto"] = mailto

            response = self.client.request(
                "/works",
                params=params,
                service=self.search_service,
            )
            payload = self._json(response)
            papers, info = parse_search_response(payload)
            total = info.get("total_results", total)
            pages.append(
                SearchPage(
                    papers=papers,
                    total_results=total,
                    start_index=retrieved,
                    items_per_page=per_page,
                    current_cursor=str(page_number),
                    next_cursor=str(page_number + 1),
                    raw=response.content,
                )
            )
            retrieved += len(papers)
            if not papers or len(papers) < per_page:
                break
            if total is not None and retrieved >= total:
                break
            page_number += 1
        return pages

    @staticmethod
    def _year_filter(start_year: int | None, end_year: int | None) -> str | None:
        if start_year and end_year:
            return f"from_publication_date:{start_year}-01-01,to_publication_date:{end_year}-12-31"
        if start_year:
            return f"from_publication_date:{start_year}-01-01"
        if end_year:
            return f"to_publication_date:{end_year}-12-31"
        return None

    # --------------------------------------------------------------- metadata

    def fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        """Look up one DOI. Returns the normalized PaperCreate payload."""
        normalized = strip_doi(doi)
        if not normalized:
            raise ValueError("A DOI is required for metadata lookup.")
        params: dict[str, Any] = {}
        mailto = self._mailto()
        if mailto:
            params["mailto"] = mailto
        response = self.client.request(
            f"/works/doi:{normalized}",
            params=params or None,
            service=self.metadata_service,
            paper_doi=normalized,
        )
        payload = self._json(response)
        from lit_harvest.providers.openalex.parser import parse_work

        return parse_work(payload).model_dump(mode="json")

    # ---------------------------------------------------------------- helpers

    def _mailto(self) -> str | None:
        return self.contact_email

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("OpenAlex returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("OpenAlex returned an unexpected payload")
        return payload
