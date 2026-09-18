"""Retry classification and bounded exponential backoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lit_harvest.models import JobStatus
from lit_harvest.providers.base import ProviderError

TRANSIENT_CODES = {
    "rate_limit",
    "transient_provider_error",
    "timeout",
    "network_error",
}
PERMANENT_CODES = {
    "not_entitled",
    "not_found",
    "authentication_error",
    "permanent_provider_error",
    "invalid_doi",
    "parse_error",
}


def retry_delay(
    attempt: int,
    *,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 300.0,
    retry_after: float | None = None,
) -> float:
    if retry_after is not None:
        return min(max(retry_after, 0.0), max_delay_seconds)
    return float(min(base_delay_seconds * (2 ** max(attempt - 1, 0)), max_delay_seconds))


def classify_error(error: ProviderError) -> JobStatus:
    if error.code == "rate_limit":
        return JobStatus.WAITING_FOR_QUOTA
    if error.code == "not_entitled":
        return JobStatus.NOT_ENTITLED
    if error.code == "not_found":
        return JobStatus.NOT_FOUND
    if error.code in {"authentication_error", "permanent_provider_error"}:
        return JobStatus.FAILED
    return JobStatus.RETRY


def next_retry_at(
    *,
    attempt: int,
    base_delay_seconds: float = 2.0,
    max_delay_seconds: float = 300.0,
    retry_after: float | None = None,
) -> datetime:
    return datetime.now(UTC) + timedelta(
        seconds=retry_delay(
            attempt,
            base_delay_seconds=base_delay_seconds,
            max_delay_seconds=max_delay_seconds,
            retry_after=retry_after,
        )
    )
