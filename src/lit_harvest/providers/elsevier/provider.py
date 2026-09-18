"""Elsevier provider: Scopus Search STANDARD and ScienceDirect FULL retrieval."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from lit_harvest.credentials.manager import CredentialManager, CredentialUnavailableError
from lit_harvest.models import Credential, HealthStatus
from lit_harvest.providers.base import (
    FullTextResult,
    HealthCheckResult,
    ProviderError,
    SearchPage,
)
from lit_harvest.providers.elsevier.client import ElsevierClient, HttpResponse
from lit_harvest.providers.elsevier.search import parse_search_response
from lit_harvest.quotas.manager import QuotaManager
from lit_harvest.storage.database import Database


class ElsevierProvider:
    name = "elsevier"
    display_name = "Elsevier"
    supports_search = True
    supports_fulltext = True
    supports_pdf = True
    supports_metadata = True

    # Service identifiers used for quotas, jobs, and health reporting.
    search_service = "scopus_search"
    fulltext_service = "article_retrieval"
    pdf_service = "article_pdf"
    SEARCH_PATH = "/content/search/scopus"
    ARTICLE_PATH = "/content/article/doi"

    def __init__(
        self,
        *,
        database: Database,
        credentials: CredentialManager,
        quotas: QuotaManager,
        client: ElsevierClient | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
    ) -> None:
        self.database = database
        self.credentials = credentials
        self.quotas = quotas
        self.client = client or ElsevierClient(
            timeout_seconds=timeout_seconds, max_attempts=max_attempts
        )

    def healthcheck(
        self, service: str | None = None, *, network: bool = True
    ) -> list[HealthCheckResult]:
        services = [service] if service else ["scopus_search", "article_retrieval"]
        results: list[HealthCheckResult] = []
        credentials = self.credentials.list_credentials(self.name)
        if not credentials:
            for item in services:
                results.append(
                    HealthCheckResult(
                        self.name,
                        item,
                        HealthStatus.UNKNOWN,
                        "No Elsevier credential configured",
                    )
                )
            return results
        for item in services:
            if not network:
                available = any(credential.secret_available for credential in credentials)
                results.append(
                    HealthCheckResult(
                        self.name,
                        item,
                        HealthStatus.HEALTHY if available else HealthStatus.UNHEALTHY,
                        "Credential detected"
                        if available
                        else "Credential configured but its secret is not available",
                    )
                )
                continue
            try:
                if item == "scopus_search":
                    self.search('TITLE-ABS-KEY("healthcheck")', max_results=1)
                else:
                    self._request_fulltext("10.1016/j.mtcomm.2026.115551", limit=False)
                results.append(
                    HealthCheckResult(self.name, item, HealthStatus.HEALTHY, "Reachable")
                )
            except ProviderError as exc:
                results.append(
                    HealthCheckResult(
                        self.name,
                        item,
                        HealthStatus.UNHEALTHY,
                        exc.message,
                        {"status_code": exc.status_code, "error_code": exc.code},
                    )
                )
            except CredentialUnavailableError as exc:
                results.append(
                    HealthCheckResult(
                        self.name,
                        item,
                        HealthStatus.UNKNOWN,
                        str(exc),
                        {"error_code": "credential_unavailable"},
                    )
                )
        return results

    # Scopus rejects count > 25 with HTTP 400, regardless of entitlements.
    MAX_PAGE_SIZE = 25

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
        exhausted_credentials: set[str] = set()
        last_error: ProviderError | None = None

        while retrieved < max_results:
            count = min(self.MAX_PAGE_SIZE, max_results - retrieved)
            params: dict[str, Any] = {
                "query": query,
                "view": "STANDARD",
                "count": count,
                "start": retrieved,
            }
            if start_year is not None:
                params["date"] = f"{start_year}-{end_year or datetime.now(UTC).year}"

            credential: Credential | None = None
            try:
                credential = self.credentials.select(
                    self.name, "scopus_search", excluded_ids=exhausted_credentials
                )
            except CredentialUnavailableError:
                if last_error is not None:
                    raise last_error from None
                raise
            try:
                secret = self.credentials.resolve_secret(credential.id)
                if not secret:
                    exhausted_credentials.add(credential.id)
                    continue
                response = self.client.request(
                    self.SEARCH_PATH,
                    params=params,
                    headers={"X-ELS-APIKey": secret, "Accept": "application/json"},
                    service="scopus_search",
                    credential_label=credential.name,
                )
            except ProviderError as exc:
                last_error = exc
                self._handle_provider_error("scopus_search", credential, exc)
                exhausted_credentials.add(credential.id)
                continue

            if credential:
                self.quotas.apply_headers(
                    provider=self.name,
                    service="scopus_search",
                    credential_id=credential.id,
                    quota_scope=credential.quota_scope,
                    headers=response.headers,
                )
                self.quotas.local_usage(
                    provider=self.name,
                    service="scopus_search",
                    credential_id=credential.id,
                    quota_scope=credential.quota_scope,
                )

            payload = self._json(response)
            papers, info = parse_search_response(payload)
            total = info.get("total_results", total)
            pages.append(
                SearchPage(
                    papers=papers,
                    total_results=total,
                    start_index=info.get("start_index", retrieved),
                    items_per_page=info.get("items_per_page", len(papers)),
                    current_cursor=None,
                    next_cursor=None,
                    raw=response.content,
                    credential=credential,
                )
            )
            retrieved += len(papers)
            if not papers or len(papers) < count:
                break
            if total is not None and retrieved >= total:
                break
        return pages

    def fetch_fulltext(self, doi: str) -> FullTextResult:
        return self._request_fulltext(doi, limit=True)

    def fetch_pdf(self, doi: str) -> FullTextResult:
        return self._request_pdf(doi)

    def _request_fulltext(self, doi: str, *, limit: bool = True) -> FullTextResult:
        excluded: set[str] = set()
        last_error: ProviderError | None = None
        while True:
            credential: Credential | None = None
            try:
                credential = self.credentials.select(
                    self.name, "article_retrieval", excluded_ids=excluded
                )
            except CredentialUnavailableError:
                if last_error is not None:
                    raise last_error from None
                raise
            try:
                secret = self.credentials.resolve_secret(credential.id)
                if not secret:
                    excluded.add(credential.id)
                    continue
                response = self.client.request(
                    f"{self.ARTICLE_PATH}/{quote(doi, safe='')}",
                    params={"view": "FULL"},
                    headers={"X-ELS-APIKey": secret, "Accept": "text/xml"},
                    service="article_retrieval",
                    credential_label=credential.name,
                    paper_doi=doi,
                )
                if limit:
                    self.quotas.apply_headers(
                        provider=self.name,
                        service="article_retrieval",
                        credential_id=credential.id,
                        quota_scope=credential.quota_scope,
                        headers=response.headers,
                    )
                    self.quotas.local_usage(
                        provider=self.name,
                        service="article_retrieval",
                        credential_id=credential.id,
                        quota_scope=credential.quota_scope,
                    )
                return FullTextResult(
                    doi=doi,
                    content=response.content,
                    content_type=response.headers.get("content-type", "text/xml"),
                    format="xml",
                    http_status=response.status_code,
                    url=response.url,
                    provider=self.name,
                    service="article_retrieval",
                    credential=credential,
                    headers=response.headers,
                )
            except ProviderError as exc:
                last_error = exc
                self._handle_provider_error("article_retrieval", credential, exc)
                excluded.add(credential.id)
                continue

    def _request_pdf(self, doi: str) -> FullTextResult:
        excluded: set[str] = set()
        last_error: ProviderError | None = None
        while True:
            credential: Credential | None = None
            try:
                credential = self.credentials.select(
                    self.name, "article_pdf", excluded_ids=excluded
                )
            except CredentialUnavailableError:
                if last_error is not None:
                    raise last_error from None
                raise
            try:
                secret = self.credentials.resolve_secret(credential.id)
                if not secret:
                    excluded.add(credential.id)
                    continue
                response = self.client.request(
                    f"{self.ARTICLE_PATH}/{quote(doi, safe='')}",
                    params={"view": "FULL", "httpAccept": "application/pdf"},
                    headers={"X-ELS-APIKey": secret, "Accept": "application/pdf"},
                    service="article_pdf",
                    credential_label=credential.name,
                    paper_doi=doi,
                )
                content_type = response.headers.get("content-type", "")
                if "application/pdf" not in content_type and not response.content.startswith(
                    b"%PDF"
                ):
                    raise ProviderError(
                        "Elsevier did not return a PDF for this article",
                        status_code=response.status_code,
                        context={"content_type": content_type},
                    )
                self.quotas.apply_headers(
                    provider=self.name,
                    service="article_pdf",
                    credential_id=credential.id,
                    quota_scope=credential.quota_scope,
                    headers=response.headers,
                )
                self.quotas.local_usage(
                    provider=self.name,
                    service="article_pdf",
                    credential_id=credential.id,
                    quota_scope=credential.quota_scope,
                    limit=10_000,
                )
                return FullTextResult(
                    doi=doi,
                    content=response.content,
                    content_type=content_type or "application/pdf",
                    format="pdf",
                    http_status=response.status_code,
                    url=response.url,
                    provider=self.name,
                    service="article_pdf",
                    credential=credential,
                    headers=response.headers,
                )
            except ProviderError as exc:
                last_error = exc
                self._handle_provider_error("article_pdf", credential, exc)
                excluded.add(credential.id)
                continue

    def _handle_provider_error(
        self, service: str, credential: Credential, error: ProviderError
    ) -> None:
        if isinstance(error, ProviderError) and error.status_code == 429:
            self.quotas.mark_cooldown(
                provider=self.name,
                service=service,
                credential_id=credential.id,
                quota_scope=credential.quota_scope,
                retry_after=error.retry_after,
                message=error.message,
            )
        elif error.status_code == 401:
            self.database.set_credential_health(
                credential.id, HealthStatus.UNHEALTHY, error.message
            )
        elif error.status_code == 403:
            self.database.set_provider_health(
                self.name,
                HealthStatus.DEGRADED,
                service=service,
                message=error.message,
            )
        self.database.record_event(
            provider=self.name,
            service=service,
            credential_id=credential.id,
            event_type="provider_error",
            level="warning",
            http_status=error.status_code,
            message=error.message,
            metadata={"error_code": error.code},
        )

    @staticmethod
    def _json(response: HttpResponse) -> dict[str, Any]:
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Elsevier returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Elsevier returned an unexpected JSON payload")
        return payload
