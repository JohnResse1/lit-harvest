"""Unpaywall provider: DOI -> every known open-access location.

Unpaywall requires a contact email (its API terms ask callers to identify
themselves) but no API key. Because it reports repository copies, it frequently
finds a free PDF where a publisher-only lookup would have spent institutional
quota. It is a lookup-only provider: it never searches for new papers.
"""

from __future__ import annotations

import json
from typing import Any

from lit_harvest.models import HealthStatus
from lit_harvest.policy import PolicyService
from lit_harvest.providers.base import (
    HealthCheckResult,
    ProviderError,
)
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.unpaywall.parser import parse_unpaywall_record
from lit_harvest.storage.database import Database


class UnpaywallProvider:
    name = "unpaywall"
    display_name = "Unpaywall"

    supports_search = False
    supports_fulltext = False
    supports_pdf = False
    supports_metadata = False
    supports_oa_lookup = True
    # Unpaywall asks callers to supply a contact email, but issues no key.
    requires_credential = False

    lookup_service = "oa_lookup"

    BASE_URL = "https://api.unpaywall.org"

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

    @property
    def configured(self) -> bool:
        """Unpaywall is only usable with a contact email, per its API terms."""
        return bool(self.contact_email)

    # ------------------------------------------------------------ healthcheck

    def healthcheck(
        self, service: str | None = None, *, network: bool = True
    ) -> list[HealthCheckResult]:
        target = service or self.lookup_service
        if not self.configured:
            return [
                HealthCheckResult(
                    self.name,
                    target,
                    HealthStatus.UNKNOWN,
                    "Set contact_email to use Unpaywall",
                )
            ]
        if not network:
            return [
                HealthCheckResult(
                    self.name, target, HealthStatus.HEALTHY, "Contact email configured"
                )
            ]
        try:
            self.fetch_oa_location("10.1038/nature12373")
        except ProviderError as exc:
            return [
                HealthCheckResult(
                    self.name,
                    target,
                    HealthStatus.UNHEALTHY,
                    exc.message,
                    {"status_code": exc.status_code, "error_code": exc.code},
                )
            ]
        return [HealthCheckResult(self.name, target, HealthStatus.HEALTHY, "Reachable")]

    # ----------------------------------------------------------------- lookup

    def fetch_oa_location(self, doi: str) -> dict[str, Any] | None:
        if not self.configured:
            return None
        normalized = _strip_doi(doi)
        if not normalized:
            return None
        response = self.client.request(
            f"/v2/{normalized}",
            params={"email": self.contact_email},
            service=self.lookup_service,
            paper_doi=normalized,
        )
        payload = self._json(response)
        if not payload.get("is_oa"):
            return None
        return parse_unpaywall_record(payload)

    def fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        """Unpaywall's record is thin, so it is exposed only for OA purposes."""
        return None

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError("Unpaywall returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Unpaywall returned an unexpected payload")
        return payload


def _strip_doi(value: str) -> str:
    text = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :]
    return text
