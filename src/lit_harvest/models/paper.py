"""Paper registry domain models."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class PaperIdentifiers(BaseModel):
    doi: str | None = None
    scopus_id: str | None = None
    eid: str | None = None
    pii: str | None = None
    pmid: str | None = None
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None
    publisher_specific: dict[str, str] = Field(default_factory=dict)

    def as_pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        schemes = (
            "doi",
            "scopus_id",
            "eid",
            "pii",
            "pmid",
            "openalex_id",
            "semantic_scholar_id",
        )
        for scheme in schemes:
            value = getattr(self, scheme)
            if value:
                pairs.append((scheme, value))
        pairs.extend((f"publisher:{key}", value) for key, value in self.publisher_specific.items())
        return pairs


class PaperCreate(BaseModel):
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    publication_year: int | None = None
    publisher: str | None = None
    document_type: str | None = None
    discovery_source: str | None = None
    identifiers: PaperIdentifiers = Field(default_factory=PaperIdentifiers)
    extra: dict[str, Any] = Field(default_factory=dict)


class Paper(PaperCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage: str = "discovered"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
