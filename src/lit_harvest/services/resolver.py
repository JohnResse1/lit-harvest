"""Resolve a DOI to the best available source.

The resolver is deliberately independent of provider implementations. It reasons
only about *capabilities*, *document quality*, and *access cost*.

Access order matters. A free open-access copy costs nothing and never touches an
institutional subscription, so it is always preferred over a publisher API. This
keeps ordinary reading off the shared quota that libraries meter and monitor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lit_harvest.providers.registry import ProviderRegistry

# Higher is better. Publisher structured XML beats OA copies, which beat PDF.
QUALITY: dict[str, int] = {
    "xml": 100,
    "html": 80,
    "pdf": 60,
    "unknown": 0,
}


def _requires_hosted_record(provider: Any) -> bool:
    """True when a provider can only serve records it already hosts."""
    return bool(getattr(provider, "fulltext_requires_hosted_record", False))


def _split_by_hosted_record(
    providers: list[Any],
) -> tuple[list[Any], list[Any]]:
    """Partition providers into (can attempt any DOI, hosted-record only)."""
    can_attempt: list[Any] = []
    hosted_only: list[Any] = []
    for provider in providers:
        (hosted_only if _requires_hosted_record(provider) else can_attempt).append(provider)
    return can_attempt, hosted_only


@dataclass(slots=True)
class CandidateSource:
    """One way a DOI could legitimately be obtained."""

    provider: str
    service: str
    format: str
    quality: int
    reason: str = ""
    # True when this route does not consume an institutional subscription.
    free_access: bool = False
    oa_status: str | None = None
    license: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "service": self.service,
            "format": self.format,
            "quality": self.quality,
            "reason": self.reason,
            "free_access": self.free_access,
            "oa_status": self.oa_status,
            "license": self.license,
            "url": self.url,
        }


@dataclass(slots=True)
class OAResult:
    """Outcome of an open-access lookup for one DOI."""

    doi: str
    is_oa: bool = False
    downloadable: bool = False
    # Downloadable file URL. Often a PDF, but structured XML (e.g. Europe PMC
    # JATS) is also valid and strictly higher quality, so the format travels
    # alongside the URL instead of being assumed.
    pdf_url: str | None = None
    file_format: str | None = None
    landing_url: str | None = None
    oa_status: str | None = None
    license: str | None = None
    version: str | None = None
    source: str | None = None
    checked: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "is_oa": self.is_oa,
            "downloadable": self.downloadable,
            "pdf_url": self.pdf_url,
            "file_format": self.file_format,
            "landing_url": self.landing_url,
            "oa_status": self.oa_status,
            "license": self.license,
            "version": self.version,
            "source": self.source,
            "checked": self.checked,
            "errors": self.errors,
        }


class Resolver:
    """Chooses which provider/service should retrieve a given DOI."""

    def __init__(self, providers: ProviderRegistry):
        self.providers = providers
        self._oa_cache: dict[str, OAResult] = {}

    # ------------------------------------------------------------------- OA

    def oa_lookup(self, doi: str, *, refresh: bool = False) -> OAResult:
        """Ask every OA-capable provider whether a free copy exists.

        Results are cached per process so repeated routing decisions for the
        same DOI do not re-query the network.
        """
        if not refresh and doi in self._oa_cache:
            return self._oa_cache[doi]

        result = OAResult(doi=doi)
        for provider in self.providers.with_capability("supports_oa_lookup"):
            lookup = getattr(provider, "fetch_oa_location", None)
            if lookup is None:
                continue
            result.checked = True
            try:
                payload = lookup(doi)
            except Exception as exc:  # noqa: BLE001 - a failed lookup never blocks retrieval
                result.errors.append(f"{provider.name}: {exc}")
                continue
            if not payload:
                continue
            result.is_oa = bool(payload.get("is_oa"))
            result.downloadable = bool(payload.get("downloadable"))
            result.pdf_url = payload.get("pdf_url") or result.pdf_url
            result.file_format = payload.get("file_format") or result.file_format
            result.landing_url = payload.get("landing_url") or result.landing_url
            result.oa_status = payload.get("oa_status") or result.oa_status
            result.license = payload.get("license") or result.license
            result.version = payload.get("version") or result.version
            result.source = provider.name
            if result.downloadable:
                break
        self._oa_cache[doi] = result
        return result

    def clear_oa_cache(self) -> None:
        self._oa_cache.clear()

    def prime_oa_cache(self, doi: str, payload: dict[str, Any]) -> None:
        """Record OA information already returned by a search.

        Search results carry open-access details, so storing them here avoids a
        second network round trip (and its pacing delay) per candidate.
        """
        if not doi:
            return
        pdf_url = payload.get("pdf_url")
        self._oa_cache[doi] = OAResult(
            doi=doi,
            is_oa=bool(payload.get("is_oa")),
            downloadable=bool(pdf_url),
            pdf_url=pdf_url,
            file_format=payload.get("file_format"),
            landing_url=payload.get("oa_url"),
            oa_status=payload.get("oa_status"),
            license=payload.get("license"),
            version=payload.get("version"),
            source=payload.get("source") or "search",
            checked=True,
        )

    # ------------------------------------------------------------- candidates

    def route_for_job(self, doi: str) -> CandidateSource | None:
        """Pick a provider for a queued job without any network access.

        Queue time must stay offline: a batch import of 500 DOIs should not make
        500 metadata lookups. The open-access decision happens when the job runs.
        """
        del doi  # routing is capability-based until execution time
        providers = list(self.providers.fulltext_providers())
        if not providers:
            return None
        # Some providers (Europe PMC) can only serve records they host, so they
        # must not be chosen for an arbitrary DOI. Prefer a provider that can
        # attempt any DOI, and only fall back to a conditional one.
        provider = next(
            (item for item in providers if not _requires_hosted_record(item)),
            providers[0],
        )
        return CandidateSource(
            provider=provider.name,
            service=getattr(provider, "fulltext_service", "article_retrieval"),
            format="xml",
            quality=QUALITY["xml"],
            reason="publisher structured full text",
        )

    def candidates(
        self,
        doi: str,
        *,
        want_pdf: bool = False,
        prefer_oa: bool = True,
    ) -> list[CandidateSource]:
        """Ranked sources for this DOI, free access first."""
        sources: list[CandidateSource] = []

        if prefer_oa:
            oa = self.oa_lookup(doi)
            if oa.downloadable and oa.pdf_url:
                # Structured OA XML outranks an OA PDF; the resolver must say so.
                oa_format = oa.file_format or "pdf"
                sources.append(
                    CandidateSource(
                        provider=oa.source or "openalex",
                        service="oa_download",
                        format=oa_format,
                        # Free access outranks everything: it costs no quota.
                        quality=QUALITY["xml"] + 50,
                        reason="open-access copy (no institutional quota used)",
                        free_access=True,
                        oa_status=oa.oa_status,
                        license=oa.license,
                        url=oa.pdf_url,
                    )
                )

        fulltext = list(self.providers.fulltext_providers())
        # An unconditional publisher route can serve any entitled DOI, so it
        # outranks a provider that can only serve records it already hosts
        # (Europe PMC). The latter stays as a lower-ranked best-effort fallback
        # rather than being described as an authoritative publisher route.
        can_attempt, conditional = _split_by_hosted_record(fulltext)
        for provider in can_attempt:
            sources.append(
                CandidateSource(
                    provider=provider.name,
                    service=getattr(provider, "fulltext_service", "article_retrieval"),
                    format="xml",
                    quality=QUALITY["xml"],
                    reason="publisher structured full text",
                )
            )
        for provider in conditional:
            sources.append(
                CandidateSource(
                    provider=provider.name,
                    service=getattr(provider, "fulltext_service", "article_retrieval"),
                    format="xml",
                    # Below a real publisher route, above nothing.
                    quality=QUALITY["xml"] - 10,
                    reason="hosted open-access full text (only for indexed records)",
                )
            )
        if want_pdf:
            for provider in self.providers.pdf_providers():
                sources.append(
                    CandidateSource(
                        provider=provider.name,
                        service=getattr(provider, "pdf_service", "article_pdf"),
                        format="pdf",
                        quality=QUALITY["pdf"],
                        reason="publisher PDF",
                    )
                )
        sources.sort(key=lambda item: (-item.quality, item.provider))
        return sources

    def best(
        self, doi: str, *, want_pdf: bool = False, prefer_oa: bool = True
    ) -> CandidateSource | None:
        matches = self.candidates(doi, want_pdf=want_pdf, prefer_oa=prefer_oa)
        return matches[0] if matches else None
