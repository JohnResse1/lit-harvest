"""Parse provider quota headers and persist quota state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from lit_harvest.models import QuotaScope, QuotaSource, QuotaState, QuotaStatus, QuotaUpdate
from lit_harvest.storage.database import Database


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def parse_reset(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    numeric = _integer(cleaned)
    if numeric is not None:
        try:
            return datetime.fromtimestamp(numeric, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = parsedate_to_datetime(cleaned)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    numeric = _integer(value)
    if numeric is not None:
        return float(max(numeric, 0))
    parsed = parse_reset(value)
    if parsed is None:
        return None
    return max((parsed - datetime.now(UTC)).total_seconds(), 0.0)


class QuotaManager:
    def __init__(self, database: Database):
        self.database = database

    def apply_headers(
        self,
        *,
        provider: str,
        service: str,
        credential_id: str | None,
        quota_scope: QuotaScope,
        headers: Mapping[str, str],
    ) -> tuple[QuotaState | None, float | None]:
        limit = _integer(_header(headers, "X-RateLimit-Limit"))
        remaining = _integer(_header(headers, "X-RateLimit-Remaining"))
        reset = parse_reset(_header(headers, "X-RateLimit-Reset"))
        retry_after = parse_retry_after(_header(headers, "Retry-After"))
        if retry_after is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=retry_after)
            reset = reset or retry_at
        if limit is None and remaining is None and reset is None:
            return None, retry_after
        status: QuotaStatus | None = None
        if retry_after is not None:
            status = QuotaStatus.COOLDOWN
        update = QuotaUpdate(
            provider=provider,
            service=service,
            credential_id=credential_id,
            limit=limit,
            remaining=remaining,
            reset_at=reset,
            source=QuotaSource.RESPONSE_HEADER,
            quota_scope=quota_scope,
            status=status,
        )
        return self.database.upsert_quota(update), retry_after

    def mark_cooldown(
        self,
        *,
        provider: str,
        service: str,
        credential_id: str | None,
        quota_scope: QuotaScope,
        retry_after: float | None,
        message: str | None = None,
    ) -> None:
        delay = retry_after if retry_after is not None else 60.0
        self.database.upsert_quota(
            QuotaUpdate(
                provider=provider,
                service=service,
                credential_id=credential_id,
                reset_at=datetime.now(UTC) + timedelta(seconds=delay),
                source=QuotaSource.RESPONSE_HEADER
                if retry_after is not None
                else QuotaSource.LOCAL_ESTIMATE,
                quota_scope=quota_scope,
                status=QuotaStatus.COOLDOWN,
                message=message,
            )
        )

    def mark_unavailable(
        self,
        *,
        provider: str,
        service: str,
        credential_id: str | None,
        quota_scope: QuotaScope,
        message: str,
    ) -> None:
        self.database.upsert_quota(
            QuotaUpdate(
                provider=provider,
                service=service,
                credential_id=credential_id,
                source=QuotaSource.LOCAL_ESTIMATE,
                quota_scope=quota_scope,
                status=QuotaStatus.EXHAUSTED,
                message=message,
            )
        )

    def local_usage(
        self,
        *,
        provider: str,
        service: str,
        credential_id: str | None,
        quota_scope: QuotaScope,
        units: int = 1,
        limit: int | None = None,
    ) -> None:
        existing = self.database.get_quota(provider, service, credential_id)
        observed_limit = existing.limit if existing and existing.limit is not None else limit
        if existing and existing.remaining is not None:
            remaining = max(existing.remaining - units, 0)
            reset_at = existing.reset_at
        elif observed_limit is not None:
            remaining = max(observed_limit - units, 0)
            reset_at = existing.reset_at if existing else None
        else:
            return
        self.database.upsert_quota(
            QuotaUpdate(
                provider=provider,
                service=service,
                credential_id=credential_id,
                limit=observed_limit,
                remaining=remaining,
                reset_at=reset_at,
                source=QuotaSource.LOCAL_ESTIMATE,
                quota_scope=quota_scope,
            )
        )
