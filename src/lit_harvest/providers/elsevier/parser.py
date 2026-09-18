"""Deterministic normalization of ScienceDirect FULL XML into PaperDocument."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from lxml import etree

from lit_harvest.models import (
    Affiliation,
    Author,
    BibliographicMetadata,
    DocumentIdentifiers,
    DocumentProvenance,
    Equation,
    Figure,
    OpenAccessMetadata,
    PaperDocument,
    Paragraph,
    PublicationDates,
    Reference,
    Section,
    Table,
)

PARSER_VERSION = "elsevier-full-xml/1.0"


def local_name(element: etree._Element) -> str:
    return str(etree.QName(element).localname)


def text_of(element: etree._Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join(part for part in element.itertext() if isinstance(part, str)).strip()
    value = " ".join(value.split())
    return value or None


def first(root: etree._Element, *names: str) -> etree._Element | None:
    wanted = {name.lower() for name in names}
    for element in root.iter():
        if isinstance(element.tag, str) and local_name(element).lower() in wanted:
            return element
    return None


def first_text(root: etree._Element, *names: str) -> str | None:
    return text_of(first(root, *names))


def all_elements(root: etree._Element, name: str) -> list[etree._Element]:
    lowered = name.lower()
    return [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and local_name(element).lower() == lowered
    ]


def _identifier(root: etree._Element) -> str | None:
    for element in root.iter():
        if isinstance(element.tag, str) and local_name(element) == "identifier":
            value = text_of(element)
            if value and "10." in value:
                return value.replace("doi:", "").replace("DOI:", "").strip()
    return first_text(root, "doi")


def _authors(root: etree._Element) -> list[Author]:
    result: list[Author] = []
    author_container = first(root, "authors")
    if author_container is None:
        return result
    candidates = [
        item
        for item in author_container.iter()
        if isinstance(item.tag, str) and local_name(item) == "author"
    ]
    for index, author in enumerate(candidates, start=1):
        given = first_text(author, "given-name", "givenname")
        surname = first_text(author, "surname", "family-name")
        full = " ".join(part for part in (given, surname) if part) or text_of(author)
        if not full:
            continue
        affiliation_ids = [
            value
            for item in author.iter()
            if isinstance(item.tag, str) and local_name(item) == "affiliation"
            for value in [item.get("id")]
            if value
        ]
        result.append(
            Author(
                given_name=given,
                surname=surname,
                full_name=full,
                email=first_text(author, "email"),
                orcid=first_text(author, "orcid"),
                affiliation_ids=affiliation_ids,
                sequence=index,
            )
        )
    return result


def _affiliations(root: etree._Element) -> list[Affiliation]:
    result: list[Affiliation] = []
    seen: set[str] = set()
    for item in all_elements(root, "affiliation"):
        identifier = item.get("id")
        name = first_text(item, "affilname", "organization", "institution")
        if not name:
            name = text_of(item)
        if not name or (identifier and identifier in seen):
            continue
        if identifier:
            seen.add(identifier)
        result.append(
            Affiliation(
                id=identifier,
                name=name,
                city=first_text(item, "city", "location"),
                country=first_text(item, "country"),
                raw=text_of(item),
            )
        )
    return result


def _abstract(root: etree._Element) -> str | None:
    candidates = all_elements(root, "abstract")
    if not candidates:
        return None

    # Elsevier FULL XML often contains a graphical abstract before the real
    # article abstract. Prefer the longest non-caption abstract body.
    best: str | None = None
    for abstract in candidates:
        paragraphs = [
            text_of(item)
            for item in abstract.iter()
            if isinstance(item.tag, str)
            and local_name(item) in {"simple-para", "para", "p"}
            and text_of(item)
        ]
        candidate = " ".join(item for item in paragraphs if item)
        if not candidate:
            candidate = text_of(abstract) or ""
        if candidate and (best is None or len(candidate) > len(best)):
            best = candidate
    return best


def _keywords(root: etree._Element) -> list[str]:
    result: list[str] = []
    for item in all_elements(root, "keyword"):
        value = text_of(item)
        if value and value not in result:
            result.append(value)
    for item in all_elements(root, "subject"):
        value = text_of(item)
        if value and value not in result:
            result.append(value)
    return result


def _paragraphs(section: etree._Element) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for item in section.iter():
        if not isinstance(item.tag, str) or local_name(item) not in {"para", "simple-para", "p"}:
            continue
        # Only paragraphs directly owned by this section, not nested sections.
        ancestor = item.getparent()
        direct = False
        while ancestor is not None and ancestor is not section:
            if local_name(ancestor) == "section":
                direct = False
                break
            ancestor = ancestor.getparent()
        else:
            direct = ancestor is section
        if direct:
            value = text_of(item)
            if value:
                paragraphs.append(Paragraph(id=item.get("id"), text=value, type=item.get("type")))
    return paragraphs


def _sections(root: etree._Element) -> list[Section]:
    section_elements = [
        item
        for item in root.iter()
        if isinstance(item.tag, str)
        and local_name(item) == "section"
        and _has_section_ancestor(item) is False
    ]
    return [_section(item) for item in section_elements]


def _has_section_ancestor(element: etree._Element) -> bool:
    ancestor = element.getparent()
    while ancestor is not None:
        if isinstance(ancestor.tag, str) and local_name(ancestor) == "section":
            return True
        ancestor = ancestor.getparent()
    return False


def _section(element: etree._Element) -> Section:
    children = [
        _section(item)
        for item in element
        if isinstance(item.tag, str) and local_name(item) == "section"
    ]
    return Section(
        section_id=element.get("id"),
        title=first_text(element, "title", "section-title"),
        paragraphs=_paragraphs(element),
        children=children,
    )


def _figures(root: etree._Element) -> list[Figure]:
    result: list[Figure] = []
    for item in all_elements(root, "figure"):
        images: list[dict[str, Any]] = []
        for image in item.iter():
            if not isinstance(image.tag, str) or local_name(image) not in {"image", "img"}:
                continue
            href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href")
            images.append(
                {
                    "url": href,
                    "resolution": image.get("resolution"),
                    "type": image.get("type"),
                }
            )
        result.append(
            Figure(
                id=item.get("id"),
                label=first_text(item, "label"),
                caption=first_text(item, "caption"),
                images=images,
            )
        )
    return result


def _tables(root: etree._Element) -> list[Table]:
    result: list[Table] = []
    for item in all_elements(root, "table"):
        rows: list[list[str]] = []
        for row in item.iter():
            if not isinstance(row.tag, str) or local_name(row) not in {"row", "tr"}:
                continue
            cells = [
                text_of(cell) or ""
                for cell in row
                if isinstance(cell.tag, str) and local_name(cell) in {"cell", "td", "th"}
            ]
            if cells:
                rows.append(cells)
        result.append(
            Table(
                id=item.get("id"),
                label=first_text(item, "label"),
                caption=first_text(item, "caption"),
                rows=rows,
            )
        )
    return result


def _equations(root: etree._Element) -> list[Equation]:
    result: list[Equation] = []
    for item in all_elements(root, "equation"):
        math = first(item, "math")
        result.append(
            Equation(
                id=item.get("id"),
                label=first_text(item, "label"),
                mathml=etree.tostring(math, encoding="unicode") if math is not None else None,
                text=text_of(item),
            )
        )
    return result


def _references(root: etree._Element) -> list[Reference]:
    result: list[Reference] = []
    for item in all_elements(root, "reference"):
        authors = [text_of(author) for author in all_elements(item, "author")]
        result.append(
            Reference(
                id=item.get("id"),
                label=first_text(item, "label"),
                doi=first_text(item, "doi"),
                source_text=text_of(item),
                authors=[author for author in authors if author],
                title=first_text(item, "title", "article-title"),
                journal=first_text(item, "journal", "journal-title"),
                year=first_text(item, "year", "date"),
            )
        )
    return result


def _date(root: etree._Element, *names: str) -> str | None:
    for name in names:
        value = first_text(root, name)
        if value:
            return value
    return None


def _open_access(root: etree._Element) -> OpenAccessMetadata:
    raw = first_text(root, "openaccess", "open-access")
    is_oa: bool | None = None
    if raw is not None:
        is_oa = raw.strip().lower() in {"1", "true", "yes", "open", "hybrid", "gold"}
    return OpenAccessMetadata(
        is_open_access=is_oa,
        type=first_text(root, "openaccessType", "open-access-type"),
        license=first_text(root, "license", "license-type"),
        sponsor=first_text(root, "sponsor"),
    )


class ElsevierFullXMLParser:
    version = PARSER_VERSION

    def parse(
        self,
        content: bytes,
        *,
        source_path: str | None = None,
        credential_label: str | None = None,
        http_status: int | None = None,
    ) -> PaperDocument:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        root = etree.fromstring(content, parser=parser)
        doi = _identifier(root)
        return PaperDocument(
            identifiers=DocumentIdentifiers(
                doi=doi,
                pii=first_text(root, "pii"),
                eid=first_text(root, "eid"),
                scopus_id=first_text(root, "scopus-id", "scopusid"),
            ),
            bibliographic=BibliographicMetadata(
                title=first_text(root, "title", "article-title"),
                journal=first_text(root, "publicationName", "journal-title", "journal"),
                issn=first_text(root, "issn"),
                volume=first_text(root, "volume"),
                issue=first_text(root, "issue"),
                article_number=first_text(root, "article-number", "article-number"),
                document_type=first_text(root, "document-type"),
                document_subtype=first_text(root, "document-subtype"),
                publisher=first_text(root, "publisher"),
            ),
            dates=PublicationDates(
                received=_date(root, "date-received"),
                revised=_date(root, "date-revised"),
                accepted=_date(root, "date-accepted"),
                online=_date(root, "date-online"),
                version_of_record=_date(root, "date-version-of-record"),
                cover=first_text(root, "coverDate"),
                indexed=_date(root, "date-indexed"),
            ),
            authors=_authors(root),
            affiliations=_affiliations(root),
            abstract=_abstract(root),
            keywords=_keywords(root),
            open_access=_open_access(root),
            sections=_sections(root),
            figures=_figures(root),
            tables=_tables(root),
            equations=_equations(root),
            references=_references(root),
            attachments=[],
            provenance=DocumentProvenance(
                provider="elsevier",
                service="article_retrieval",
                format="xml",
                source_path=source_path,
                parser_version=self.version,
                acquired_at=datetime.now(UTC),
                credential_label=credential_label,
                http_status=http_status,
                sha256=sha256(content).hexdigest(),
            ),
        )
