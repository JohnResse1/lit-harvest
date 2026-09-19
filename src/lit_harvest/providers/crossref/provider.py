"""Crossref provider: key-free DOI metadata and TDM link discovery.

Crossref requires no credentials. Supplying a contact email is optional but
puts requests in the "polite pool", which is the recommended etiquette for
programmatic use. This provider never downloads full text itself: it surfaces
the publisher's registered text-mining links so the resolver can decide
whether a legitimate, entitled route exists.
"""

from __future__ import annotations

import json
from typing import Any

from lit_harvest.models import HealthStatus
from lit_harvest.policy import PolicyService
from lit_harvest.providers.base import (
    HealthCheckResult,
    NotFoundError,
    ProviderError,
    SearchPage,
)
from lit_harvest.providers.crossref.parser import (
    extract_tdm_links,
    parse_crossref_record,
    parse_search_response,
)
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.storage.database import Database


class CrossrefProvider:
    name = "crossref"
    display_name = "Crossref"

    supports_search = True
    supports_fulltext = False
    supports_pdf = False
    supports_metadata = True
    # Crossref reports publisher TDM routes, which is how open and entitled
    # machine-readable full text is discovered across publishers.
    supports_tdm_links = True
    supports_oa_lookup = False
    requires_credential = False

    search_service = "crossref_search"
    metadata_service = "crossref_lookup"

    BASE_URL = "https://api.crossref.org"
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

    # ------------------------------------------------------------ healthcheck

    def healthcheck(
        self, service: str | None = None, *, network: bool = True
    ) -> list[HealthCheckResult]:
        services = [service] if service else [self.search_service, self.metadata_service]
        if not network:
            return [
                HealthCheckResult(self.name, item, HealthStatus.HEALTHY, "No credentials required")
                for item in services
            ]
        try:
            self.search("battery", max_results=1)
            return [
                HealthCheckResult(self.name, item, HealthStatus.HEALTHY, "Reachable")
                for item in services
            ]
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
                "query.bibliographic": query,
                "rows": page_size,
                "cursor": cursor,
                "select": (
                    "DOI,title,author,container-title,short-container-title,publisher,"
                    "type,issued,published-print,published-online,created,ISSN,volume,"
                    "issue,page,article-number,abstract,subject,link,license,"
                    "reference-count,is-referenced-by-count,URL"
                ),
            }
            filters = self._date_filter(start_year, end_year)
            if filters:
                params["filter"] = filters
            if self.contact_email:
                params["mailto"] = self.contact_email
            response = self.client.request(
                "/works", params=params, service=self.search_service
            )
            payload = self._json(response)
            papers, info = parse_search_response(payload)
            total = info.get("total_results", total)
            message = payload.get("message") or {}
            next_cursor = message.get("next-cursor") if isinstance(message, dict) else None
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
    def _date_filter(start_year: int | None, end_year: int | None) -> str | None:
        parts: list[str] = []
        if start_year:
            parts.append(f"from-pub-date:{start_year}-01-01")
        if end_year:
            parts.append(f"until-pub-date:{end_year}-12-31")
        return ",".join(parts) or None

    # --------------------------------------------------------------- metadata

    def fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        normalized = _strip_doi(doi)
        if not normalized:
            raise ValueError("A DOI is required for metadata lookup.")
        response = self.client.request(
            f"/works/{normalized}",
            service=self.metadata_service,
            paper_doi=normalized,
        )
        payload = self._json(response)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise NotFoundError("Crossref returned no work record.")
        return parse_crossref_record(message).model_dump(mode="json")

    def fetch_tdm_links(self, doi: str) -> list[dict[str, str]]:
        """Publisher-registered text-mining routes for one DOI.

        These are discovery pointers, not a grant of access: fetching them still
        requires the caller's own entitlement.
        """
        normalized = _strip_doi(doi)
        if not normalized:
            return []
        # NOTE: the single-work route rejects the `select` parameter (HTTP 400);
        # only the works search route accepts it.
        response = self.client.request(
            f"/works/{normalized}",
            service=self.metadata_service,
            paper_doi=normalized,
        )
        payload = self._json(response)
        message = payload.get("message")
        if not isinstance(message, dict):
            return []
        return extract_tdm_links(message)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Crossref returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Crossref returned an unexpected payload")
        return payload


def _strip_doi(value: str) -> str:
    text = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :]
    return text
