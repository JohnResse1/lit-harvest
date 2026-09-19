"""Shared HTTP client with bounded retries and provider error mapping.

Both the Elsevier and OpenAlex clients need the same behaviour: respect the
pacing policy, retry transient failures with bounded backoff, and translate
HTTP status codes into the domain errors the scheduler understands.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from lit_harvest.providers.base import (
    AuthenticationError,
    EntitlementError,
    NotFoundError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    TransientProviderError,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str
    elapsed_ms: int
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class JsonHttpClient:
    """Minimal GET client used by JSON-based providers."""

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        base_url: str,
        provider: str,
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        policy: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self._transport = transport
        self._sleep = sleep
        self._policy = policy

    def request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        service: str,
        credential_label: str | None = None,
        paper_doi: str | None = None,
        job_id: str | None = None,
    ) -> HttpResponse:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": f"lit-harvest/0.1.0 ({self.provider})",
            **(headers or {}),
        }
        if self._policy is not None:
            self._policy.wait_turn(self.provider, service)

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self._transport,
                    follow_redirects=True,
                ) as client:
                    response = client.get(
                        f"{self.base_url}{path}", params=params, headers=request_headers
                    )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "provider_request provider=%s service=%s credential=%s doi=%s job=%s "
                    "status=%s duration_ms=%s attempt=%s",
                    self.provider,
                    service,
                    credential_label,
                    paper_doi,
                    job_id,
                    response.status_code,
                    elapsed_ms,
                    attempt,
                )
                if response.status_code in self.RETRYABLE_STATUS:
                    retry_after = self._retry_after(response.headers)
                    if attempt < self.max_attempts:
                        delay = retry_after if retry_after is not None else self._backoff(attempt)
                        self._sleep(delay)
                        last_error = self._error_for_response(response, retry_after=retry_after)
                        continue
                    raise self._error_for_response(response, retry_after=retry_after)
                if response.status_code in {400, 422}:
                    raise PermanentProviderError(
                        self._response_message(response),
                        status_code=response.status_code,
                        context={"service": service, "path": path},
                    )
                if response.status_code == 401:
                    raise AuthenticationError(
                        self._response_message(response),
                        status_code=response.status_code,
                        context={"service": service, "path": path},
                    )
                if response.status_code == 403:
                    raise EntitlementError(
                        self._response_message(response),
                        status_code=response.status_code,
                        context={"service": service, "path": path},
                    )
                if response.status_code == 404:
                    raise NotFoundError(
                        self._response_message(response),
                        status_code=response.status_code,
                        context={"service": service, "path": path},
                    )
                response.raise_for_status()
                return HttpResponse(
                    status_code=response.status_code,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    content=response.content,
                    url=str(response.url),
                    elapsed_ms=elapsed_ms,
                    request_id=response.headers.get("x-request-id"),
                )
            except ProviderError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise TransientProviderError(
                    str(exc), context={"service": service, "path": path}
                ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise TransientProviderError(
                    str(exc), context={"service": service, "path": path}
                ) from exc
        raise TransientProviderError(
            str(last_error or "request failed"), context={"service": service}
        )

    @staticmethod
    def _backoff(attempt: int) -> float:
        return float(min(2 ** (attempt - 1), 8))

    @staticmethod
    def _retry_after(headers: httpx.Headers) -> float | None:
        raw = headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(float(str(raw)), 0.0)
        except ValueError:
            return None

    @staticmethod
    def _response_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text[:500] if text else f"HTTP {response.status_code}"
        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value
        return f"HTTP {response.status_code}"

    def _error_for_response(
        self, response: httpx.Response, *, retry_after: float | None
    ) -> ProviderError:
        message = self._response_message(response)
        if response.status_code == 429:
            return RateLimitError(message, status_code=429, retry_after=retry_after)
        return TransientProviderError(
            message, status_code=response.status_code, retry_after=retry_after
        )
