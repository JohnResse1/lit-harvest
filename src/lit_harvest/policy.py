"""Conservative usage policy that protects shared institutional access.

Publishers meter access per institution, not per person. A single researcher
running an aggressive loop can therefore affect everyone at their university.
This module enforces a deliberately gentle default pace and a daily ceiling so
the tool stays inside normal research use.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from lit_harvest.storage.database import Database


class PolicyLimitError(RuntimeError):
    """Raised when a daily usage ceiling has been reached."""

    code = "policy_limit"

    def __init__(self, message: str, *, provider: str, service: str, limit: int) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.service = service
        self.limit = limit


@dataclass(slots=True)
class ProviderPolicy:
    """Per-service pacing and daily ceilings for one provider.

    Intervals are intentionally generous. They exist to keep aggregate usage
    defensible, not to hit the publisher's technical limits.
    """

    fulltext_min_interval_seconds: float = 60.0
    pdf_min_interval_seconds: float = 120.0
    search_min_interval_seconds: float = 5.0

    fulltext_daily_limit: int | None = 100
    pdf_daily_limit: int | None = 50
    search_daily_limit: int | None = 200

    # Randomise waits by this fraction so requests do not form a fixed rhythm.
    jitter_ratio: float = 0.25

    def min_interval(self, service: str) -> float:
        if service.endswith("pdf") or "pdf" in service:
            return self.pdf_min_interval_seconds
        if "search" in service:
            return self.search_min_interval_seconds
        if "article" in service or "fulltext" in service:
            return self.fulltext_min_interval_seconds
        return self.fulltext_min_interval_seconds

    def daily_limit(self, service: str) -> int | None:
        if service.endswith("pdf") or "pdf" in service:
            return self.pdf_daily_limit
        if "search" in service:
            return self.search_daily_limit
        return self.fulltext_daily_limit

    def jittered_interval(self, service: str, rng: random.Random | None = None) -> float:
        base = self.min_interval(service)
        if base <= 0 or self.jitter_ratio <= 0:
            return base
        source = rng or random
        spread = base * self.jitter_ratio
        return max(base - spread + source.random() * spread * 2, 0.0)


#: Which download format/service maps to which policy counter.
SERVICE_KINDS = {
    "article_retrieval": "fulltext",
    "article_pdf": "pdf",
    "scopus_search": "search",
}

DEFAULT_POLICY = ProviderPolicy()

PROVIDER_POLICIES: dict[str, ProviderPolicy] = {
    "elsevier": ProviderPolicy(
        fulltext_min_interval_seconds=60.0,
        pdf_min_interval_seconds=120.0,
        search_min_interval_seconds=5.0,
        fulltext_daily_limit=100,
        pdf_daily_limit=50,
        search_daily_limit=200,
        jitter_ratio=0.25,
    ),
}


class PolicyService:
    """Enforces pacing and daily ceilings for provider calls."""

    def __init__(
        self,
        database: Database,
        *,
        policies: dict[str, ProviderPolicy] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.database = database
        self.policies = {**PROVIDER_POLICIES, **(policies or {})}
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last_call: dict[tuple[str, str], float] = {}
        self._rng = random.Random()

    # ---------------------------------------------------------------- policy

    def policy_for(self, provider: str) -> ProviderPolicy:
        return self.policies.get(provider, DEFAULT_POLICY)

    def describe(self, provider: str) -> dict[str, object]:
        policy = self.policy_for(provider)
        return {
            "provider": provider,
            "fulltext_min_interval_seconds": policy.fulltext_min_interval_seconds,
            "pdf_min_interval_seconds": policy.pdf_min_interval_seconds,
            "search_min_interval_seconds": policy.search_min_interval_seconds,
            "fulltext_daily_limit": policy.fulltext_daily_limit,
            "pdf_daily_limit": policy.pdf_daily_limit,
            "search_daily_limit": policy.search_daily_limit,
            "jitter_ratio": policy.jitter_ratio,
        }

    # ----------------------------------------------------------------- usage

    def usage_today(self, provider: str, service: str) -> int:
        """How many successful calls of this kind happened in the last 24h."""
        since = datetime.now(UTC) - timedelta(days=1)
        with self.database.session() as session:
            from sqlalchemy import func, select

            from lit_harvest.storage.database import DownloadRow

            if service.endswith("pdf") or "pdf" in service:
                statement = (
                    select(func.count())
                    .select_from(DownloadRow)
                    .where(
                        DownloadRow.provider == provider,
                        DownloadRow.status == "success",
                        DownloadRow.format == "pdf",
                        DownloadRow.acquired_at >= since,
                    )
                )
                return int(session.scalar(statement) or 0)

            if "search" in service:
                # Search calls are not stored as downloads; report from events.
                from lit_harvest.storage.database import ProviderEventRow

                statement = (
                    select(func.count())
                    .select_from(ProviderEventRow)
                    .where(
                        ProviderEventRow.provider == provider,
                        ProviderEventRow.service == service,
                        ProviderEventRow.created_at >= since,
                    )
                )
                return int(session.scalar(statement) or 0)

            statement = (
                select(func.count())
                .select_from(DownloadRow)
                .where(
                    DownloadRow.provider == provider,
                    DownloadRow.status == "success",
                    DownloadRow.service == service,
                    DownloadRow.acquired_at >= since,
                )
            )
            return int(session.scalar(statement) or 0)

    def check_daily(self, provider: str, service: str) -> None:
        """Raise if this provider/service has hit its daily ceiling."""
        policy = self.policy_for(provider)
        limit = policy.daily_limit(service)
        if limit is None:
            return
        used = self.usage_today(provider, service)
        if used >= limit:
            kind = SERVICE_KINDS.get(service, "requests")
            raise PolicyLimitError(
                (
                    f"Daily {kind} limit reached for {provider}: {used}/{limit} in the last 24 "
                    "hours. This cap protects the shared institutional subscription. "
                    "It resets automatically; you can also raise it in config.yaml."
                ),
                provider=provider,
                service=service,
                limit=limit,
            )

    # -------------------------------------------------------------- throttle

    def wait_turn(self, provider: str, service: str) -> float:
        """Sleep if needed so consecutive calls stay at a gentle pace."""
        policy = self.policy_for(provider)
        interval = policy.jittered_interval(service, self._rng)
        if interval <= 0:
            return 0.0
        key = (provider, service)
        now = self._monotonic()
        with self._lock:
            previous = self._last_call.get(key)
            delay = 0.0 if previous is None else max(interval - (now - previous), 0.0)
            self._last_call[key] = now + delay
        if delay > 0:
            self._sleep(delay)
        return delay

    def mark_call(self, provider: str, service: str) -> None:
        key = (provider, service)
        with self._lock:
            self._last_call[key] = self._monotonic()
