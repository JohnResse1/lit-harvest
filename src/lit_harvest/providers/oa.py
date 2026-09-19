"""Download openly licensed full text without touching publisher APIs.

An open-access copy is already free to read, so retrieving it consumes no
institutional subscription quota and does not contribute to the usage patterns
libraries monitor. Free copies are therefore preferred whenever they exist.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from lit_harvest.providers.base import PermanentProviderError, TransientProviderError


class OpenAccessFetcher:
    """Fetches a file from an open-access location reported by a metadata source."""

    name = "openaccess"
    service = "oa_download"

    MAX_BYTES = 100 * 1024 * 1024  # refuse implausibly large responses
    ACCEPTED_TYPES = ("application/pdf", "application/xml", "text/xml", "text/html")

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_redirects: int = 5,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._transport = transport
        self._sleep = sleep
        self.max_redirects = max_redirects

    def fetch(self, url: str) -> dict[str, Any]:
        """Return the file bytes and metadata for an OA URL."""
        if not url.lower().startswith(("http://", "https://")):
            raise PermanentProviderError(f"Refusing to fetch a non-HTTP URL: {url}")

        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self._transport,
            follow_redirects=True,
            max_redirects=self.max_redirects,
            headers={"User-Agent": "lit-harvest/0.1.0 (open-access retrieval)"},
        ) as client:
            try:
                response = client.get(url)
            except httpx.TimeoutException as exc:
                raise TransientProviderError(f"Timed out fetching OA copy: {exc}") from exc
            except httpx.HTTPError as exc:
                raise TransientProviderError(f"Failed to fetch OA copy: {exc}") from exc

        if response.status_code == 404:
            raise PermanentProviderError(
                "The open-access location no longer exists.", status_code=404
            )
        if response.status_code in {401, 403}:
            raise PermanentProviderError(
                "The open-access location refused access; it may have moved.",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise TransientProviderError(
                f"OA host returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if len(response.content) > self.MAX_BYTES:
            raise PermanentProviderError("The open-access file is unexpectedly large.")
        if not response.content:
            raise PermanentProviderError("The open-access location returned an empty file.")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        detected = self._detect_format(response.content, content_type)
        if detected is None:
            raise PermanentProviderError(
                f"The open-access location did not return a supported document "
                f"(content-type: {content_type or 'unknown'})."
            )
        return {
            "url": str(response.url),
            "content": response.content,
            "content_type": content_type or detected,
            "format": detected,
            "http_status": response.status_code,
        }

    @staticmethod
    def _detect_format(content: bytes, content_type: str) -> str | None:
        if content.startswith(b"%PDF"):
            return "pdf"
        stripped = content.lstrip()[:200].lower()
        if stripped.startswith(b"<?xml"):
            return "xml"
        if stripped.startswith(b"<"):
            return "html"
        if content_type == "application/pdf":
            return "pdf"
        if "xml" in content_type:
            return "xml"
        if "html" in content_type:
            return "html"
        return None
