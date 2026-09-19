"""Springer Nature provider.

Springer issues **separate API keys per API**, which is why credentials declare
a `services` allowlist:

* ``meta``       -> `/meta/v2/json`        search + metadata for all content
* ``openaccess`` -> `/openaccess/json`     the same shape, OA records only

Both endpoints share one record schema, so one parser serves both. Neither
serves publisher full text directly; when a record is open access, this provider
reports the publisher-hosted PDF URL so the shared open-access fetcher can
download it without touching any subscription quota.
"""

from __future__ import annotations

import json
from typing import Any

from lit_harvest.credentials.manager import CredentialManager, CredentialUnavailableError
from lit_harvest.models import Credential, HealthStatus
from lit_harvest.policy import PolicyService
from lit_harvest.providers.base import (
    HealthCheckResult,
    ProviderError,
    SearchPage,
)
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.springer.parser import parse_springer_response
from lit_harvest.storage.database import Database


class SpringerProvider:
    name = "springer"
    display_name = "Springer Nature"

    supports_search = True
    supports_fulltext = False
    supports_pdf = False
    supports_metadata = True
    supports_oa_lookup = True

    search_service = "springer_meta"
    metadata_service = "springer_meta"
    oa_service = "springer_openaccess"

    BASE_URL = "https://api.springernature.com"
    META_PATH = "/meta/v2/json"
    OA_PATH = "/openaccess/json"
    MAX_PAGE_SIZE = 100

    def __init__(
        self,
        *,
        database: Database,
        credentials: CredentialManager,
        quotas: Any | None = None,
        client: JsonHttpClient | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
        policy: PolicyService | None = None,
    ) -> None:
        self.database = database
        self.credentials = credentials
        self.quotas = quotas
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
        services = [service] if service else [self.search_service, self.oa_service]
        results: list[HealthCheckResult] = []
        if not network:
            for item in services:
                usable = self._has_credential(item)
                results.append(
                    HealthCheckResult(
                        self.name,
                        item,
                        HealthStatus.HEALTHY if usable else HealthStatus.UNKNOWN,
                        "Credential detected" if usable else "No credential configured",
                    )
                )
            return results

        for item in services:
            try:
                if item == self.oa_service:
                    self._request(self.OA_PATH, {"q": "battery", "p": 1}, self.oa_service)
                else:
                    self.search("battery", max_results=1)
                results.append(
                    HealthCheckResult(self.name, item, HealthStatus.HEALTHY, "Reachable")
                )
            except CredentialUnavailableError as exc:
                results.append(HealthCheckResult(self.name, item, HealthStatus.UNKNOWN, str(exc)))
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
        return results

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
        excluded: set[str] = set()
        last_error: ProviderError | None = None

        while retrieved < max_results:
            page_size = min(self.MAX_PAGE_SIZE, max_results - retrieved)
            params: dict[str, Any] = {
                "q": self._express_query(query, start_year, end_year),
                # Springer paging: `s` is the 1-based start record, `p` the page size.
                "s": retrieved + 1,
                "p": page_size,
            }
            try:
                credential = self.credentials.select(
                    self.name, self.search_service, excluded_ids=excluded
                )
            except CredentialUnavailableError:
                if last_error is not None:
                    raise last_error from None
                raise
            try:
                response = self._request(self.META_PATH, params, self.search_service, credential)
            except ProviderError as exc:
                last_error = exc
                excluded.add(credential.id)
                if exc.status_code in {401, 403}:
                    self.database.set_credential_health(
                        credential.id, HealthStatus.UNHEALTHY, exc.message
                    )
                continue

            payload = self._json(response)
            papers, info = parse_springer_response(payload)
            total = info.get("total_results", total)
            pages.append(
                SearchPage(
                    papers=papers,
                    total_results=total,
                    start_index=retrieved,
                    items_per_page=page_size,
                    current_cursor=str(retrieved),
                    next_cursor=str(retrieved + len(papers)),
                    raw=response.content,
                    credential=credential,
                )
            )
            retrieved += len(papers)
            if not papers or len(papers) < page_size:
                break
            if total is not None and retrieved >= total:
                break
        return pages

    @staticmethod
    def _express_query(query: str, start_year: int | None, end_year: int | None) -> str:
        """Springer uses its own query syntax; add a year filter when asked.

        A bare natural-language query works as-is, so we only wrap it when a
        year range is requested.
        """
        if start_year is None and end_year is None:
            return query
        start = f"{start_year}-01-01" if start_year else "1900-01-01"
        end = f"{end_year}-12-31" if end_year else "2100-12-31"
        return f"({query}) datewithin:{start} {end}"

    # --------------------------------------------------- metadata and OA lookup

    def fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        normalized = self._normalize_doi(doi)
        response = self._request(
            self.META_PATH, {"q": f"doi:{normalized}", "p": 1}, self.metadata_service
        )
        papers, _ = parse_springer_response(self._json(response))
        return papers[0].model_dump(mode="json") if papers else None

    def fetch_oa_location(self, doi: str) -> dict[str, Any] | None:
        """Report a publisher-hosted open-access PDF when one exists.

        The Meta API is queried first on purpose: it exposes `format=pdf` URLs,
        while the OpenAccess API only returns a DOI landing page. The OpenAccess
        API is used as a fallback when no Meta credential is configured, because
        it still confirms an article is free to read.
        """
        normalized = self._normalize_doi(doi)
        order: list[tuple[str, str]] = []
        if self._has_credential(self.metadata_service):
            order.append((self.metadata_service, self.META_PATH))
        if self._has_credential(self.oa_service):
            order.append((self.oa_service, self.OA_PATH))
        if not order:
            order.append((self.metadata_service, self.META_PATH))

        for service, path in order:
            try:
                response = self._request(path, {"q": f"doi:{normalized}", "p": 1}, service)
            except ProviderError:
                continue
            papers, _ = parse_springer_response(self._json(response))
            if not papers:
                continue
            extra = papers[0].extra or {}
            oa = extra.get("open_access") or {}
            if not isinstance(oa, dict) or not oa.get("is_oa"):
                # A definitive "not open access" answer; no need to try further.
                return None
            pdf_url = oa.get("pdf_url")
            return {
                "doi": normalized,
                "is_oa": True,
                "oa_status": oa.get("oa_status") or "open",
                "license": oa.get("license"),
                "version": oa.get("version"),
                "pdf_url": pdf_url,
                "landing_url": oa.get("oa_url"),
                "downloadable": bool(pdf_url),
                "source": self.name,
            }
        return None

    # ---------------------------------------------------------------- helpers

    def _has_credential(self, service: str) -> bool:
        try:
            self.credentials.peek(self.name, service)
        except CredentialUnavailableError:
            return False
        return True

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        from lit_harvest.storage.files import normalize_doi

        return normalize_doi(doi)

    def _request(
        self,
        path: str,
        params: dict[str, Any],
        service: str,
        credential: Credential | None = None,
    ) -> Any:
        selected = credential
        excluded: set[str] = set()
        last_error: ProviderError | None = None
        while True:
            if selected is None:
                try:
                    selected = self.credentials.select(self.name, service, excluded_ids=excluded)
                except CredentialUnavailableError:
                    if last_error is not None:
                        raise last_error from None
                    raise
            secret = self.credentials.resolve_secret(selected.id)
            if not secret:
                excluded.add(selected.id)
                selected = None
                continue
            try:
                return self.client.request(
                    path,
                    params={**params, "api_key": secret},
                    service=service,
                    credential_label=selected.name,
                )
            except ProviderError as exc:
                last_error = exc
                failing_id = selected.id
                excluded.add(failing_id)
                selected = None
                if exc.status_code in {401, 403}:
                    self.database.set_credential_health(
                        failing_id, HealthStatus.UNHEALTHY, exc.message
                    )
                continue

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Springer returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Springer returned an unexpected payload")
        return payload
