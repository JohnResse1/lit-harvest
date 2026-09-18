"""Provider-agnostic normalized paper document models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentIdentifiers(BaseModel):
    doi: str | None = None
    pii: str | None = None
    eid: str | None = None
    scopus_id: str | None = None
    pmid: str | None = None
    publisher_specific: dict[str, str] = Field(default_factory=dict)


class BibliographicMetadata(BaseModel):
    title: str | None = None
    journal: str | None = None
    issn: str | None = None
    volume: str | None = None
    issue: str | None = None
    article_number: str | None = None
    document_type: str | None = None
    document_subtype: str | None = None
    publisher: str | None = None


class PublicationDates(BaseModel):
    received: str | None = None
    revised: str | None = None
    accepted: str | None = None
    online: str | None = None
    version_of_record: str | None = None
    cover: str | None = None
    indexed: str | None = None


class Affiliation(BaseModel):
    id: str | None = None
    name: str | None = None
    city: str | None = None
    country: str | None = None
    raw: str | None = None


class Author(BaseModel):
    given_name: str | None = None
    surname: str | None = None
    full_name: str | None = None
    email: str | None = None
    orcid: str | None = None
    affiliation_ids: list[str] = Field(default_factory=list)
    sequence: int | None = None


class Paragraph(BaseModel):
    id: str | None = None
    text: str
    type: str | None = None


class Section(BaseModel):
    section_id: str | None = None
    title: str | None = None
    paragraphs: list[Paragraph] = Field(default_factory=list)
    children: list["Section"] = Field(default_factory=list)


class Figure(BaseModel):
    id: str | None = None
    label: str | None = None
    caption: str | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)


class Table(BaseModel):
    id: str | None = None
    label: str | None = None
    caption: str | None = None
    rows: list[list[str]] = Field(default_factory=list)


class Equation(BaseModel):
    id: str | None = None
    label: str | None = None
    mathml: str | None = None
    text: str | None = None


class Reference(BaseModel):
    id: str | None = None
    label: str | None = None
    doi: str | None = None
    source_text: str | None = None
    authors: list[str] = Field(default_factory=list)
    title: str | None = None
    journal: str | None = None
    year: str | None = None


class Attachment(BaseModel):
    name: str
    url: str | None = None
    content_type: str | None = None
    local_path: str | None = None
    kind: str | None = None


class OpenAccessMetadata(BaseModel):
    is_open_access: bool | None = None
    type: str | None = None
    license: str | None = None
    sponsor: str | None = None


class DocumentProvenance(BaseModel):
    provider: str
    service: str
    format: str
    source_path: str | None = None
    parser_version: str
    acquired_at: datetime | None = None
    credential_label: str | None = None
    http_status: int | None = None
    sha256: str | None = None


class PaperDocument(BaseModel):
    identifiers: DocumentIdentifiers = Field(default_factory=DocumentIdentifiers)
    bibliographic: BibliographicMetadata = Field(default_factory=BibliographicMetadata)
    dates: PublicationDates = Field(default_factory=PublicationDates)
    authors: list[Author] = Field(default_factory=list)
    affiliations: list[Affiliation] = Field(default_factory=list)
    abstract: str | None = None
    keywords: list[str] = Field(default_factory=list)
    open_access: OpenAccessMetadata = Field(default_factory=OpenAccessMetadata)
    sections: list[Section] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    equations: list[Equation] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    provenance: DocumentProvenance

    def counts(self) -> dict[str, int]:
        return {
            "sections": len(self.sections),
            "figures": len(self.figures),
            "tables": len(self.tables),
            "references": len(self.references),
        }
