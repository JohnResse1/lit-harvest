"""Provider contracts shared by acquisition services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from lit_harvest.models.credential import Credential
from lit_harvest.models.enums import HealthStatus
from lit_harvest.models.paper import PaperCreate


class ProviderError(Exception):
    """Base provider failure with retry and scheduling semantics."""

    code = "provider_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        self.context = context or {}


class AuthenticationError(ProviderError):
    code = "authentication_error"


class EntitlementError(ProviderError):
    code = "not_entitled"


class NotFoundError(ProviderError):
    code = "not_found"


def user_message(error: ProviderError) -> str:
    """Short, human-readable text that never includes a raw provider payload."""
    if error.code == "not_found":
        return (
            "Elsevier could not find this DOI. Check the DOI and that the article is "
            "available in ScienceDirect."
        )
    if error.code == "authentication_error":
        return "Elsevier rejected the API key. Store a valid key with `lit-harvest auth set`."
    if error.code == "not_entitled":
        return (
            "Your account is not entitled to this article. The API key works, but your "
            "institution or account cannot access this content."
        )
    if error.code == "rate_limit":
        return "The publisher rate limit was reached. The request will be retried later."
    message = (error.message or "").strip()
    if message.startswith("<") or len(message) > 300:
        return "The publisher request failed."
    return message or "The publisher request failed."


class RateLimitError(ProviderError):
    code = "rate_limit"
    retryable = True


class TransientProviderError(ProviderError):
    code = "transient_provider_error"
    retryable = True


class PermanentProviderError(ProviderError):
    code = "permanent_provider_error"


@dataclass(slots=True)
class HealthCheckResult:
    provider: str
    service: str
    status: HealthStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchPage:
    papers: list[PaperCreate]
    total_results: int | None
    start_index: int
    items_per_page: int
    current_cursor: str | None
    next_cursor: str | None
    raw: bytes
    credential: Credential | None = None


@dataclass(slots=True)
class FullTextResult:
    doi: str
    content: bytes
    content_type: str
    format: str
    http_status: int
    url: str
    provider: str
    service: str
    credential: Credential | None
    headers: dict[str, str] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    display_name: str

    def healthcheck(
        self, service: str | None = None, *, network: bool = True
    ) -> list[HealthCheckResult]: ...

    def search(
        self,
        query: str,
        *,
        max_results: int,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[SearchPage]: ...

    def fetch_fulltext(self, doi: str) -> FullTextResult: ...
