"""Resolve a DOI to the best available source.

The resolver is deliberately independent of provider implementations. It reasons
only about *capabilities* and *document quality*, never about Elsevier specifics,
so adding a publisher does not change this file.
"""

from __future__ import annotations

from dataclasses import dataclass

from lit_harvest.providers.registry import ProviderRegistry

# Higher is better. Publisher structured XML beats OA copies, which beat PDF.
QUALITY: dict[str, int] = {
    "xml": 100,
    "html": 80,
    "pdf": 60,
    "unknown": 0,
}


@dataclass(slots=True)
class CandidateSource:
    """One way a DOI could legitimately be obtained."""

    provider: str
    service: str
    format: str
    quality: int
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "service": self.service,
            "format": self.format,
            "quality": self.quality,
            "reason": self.reason,
        }


class Resolver:
    """Chooses which provider/service should retrieve a given DOI."""

    def __init__(self, providers: ProviderRegistry):
        self.providers = providers

    def candidates(self, doi: str, *, want_pdf: bool = False) -> list[CandidateSource]:
        """Ranked list of sources that could supply this DOI.

        `doi` is accepted for future per-DOI routing (OA lookups, publisher
        ownership); today the ranking is capability-driven.
        """
        sources: list[CandidateSource] = []
        for provider in self.providers.fulltext_providers():
            sources.append(
                CandidateSource(
                    provider=provider.name,
                    service=getattr(provider, "fulltext_service", "article_retrieval"),
                    format="xml",
                    quality=QUALITY["xml"],
                    reason="publisher structured full text",
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

    def best(self, doi: str, *, want_pdf: bool = False) -> CandidateSource | None:
        matches = self.candidates(doi, want_pdf=want_pdf)
        return matches[0] if matches else None
