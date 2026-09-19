"""Deterministic JATS XML parser.

JATS (the NLM Journal Archiving and Interchange DTD) is the dominant
machine-readable full-text format across open-access literature. Europe PMC,
PubMed Central, and a growing share of publishers expose articles as JATS, so a
single parser here covers far more ground than one bespoke parser per publisher.

The parser is namespace-agnostic (JATS ships under several DTD URLs) and never
uses regex on markup. It does not attempt OCR or layout recovery: it reads only
the structure the publisher already encoded.
"""

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
from lit_harvest.parsers.base import ParseContext

PARSER_VERSION = "jats-xml/1.0"


def local_name(element: etree._Element) -> str:
    return str(etree.QName(element).localname)


def text_of(element: etree._Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join(part for part in element.itertext() if isinstance(part, str))
    value = " ".join(value.split())
    return value or None


def children(element: etree._Element, name: str) -> list[etree._Element]:
    lowered = name.lower()
    return [
        child
        for child in element
        if isinstance(child.tag, str) and local_name(child).lower() == lowered
    ]


def descendants(element: etree._Element, name: str) -> list[etree._Element]:
    lowered = name.lower()
    return [
        item
        for item in element.iter()
        if isinstance(item.tag, str) and local_name(item).lower() == lowered
    ]


def first_child(element: etree._Element, *names: str) -> etree._Element | None:
    wanted = {name.lower() for name in names}
    for child in element:
        if isinstance(child.tag, str) and local_name(child).lower() in wanted:
            return child
    return None


def first_descendant(element: etree._Element, *names: str) -> etree._Element | None:
    wanted = {name.lower() for name in names}
    for item in element.iter():
        if isinstance(item.tag, str) and local_name(item).lower() in wanted:
            return item
    return None


def _text_at(element: etree._Element, *path: str) -> str | None:
    current: etree._Element | None = element
    for name in path:
        if current is None:
            return None
        current = first_child(current, name)
    return text_of(current)


# ------------------------------------------------------------------ metadata


def _article_id(root: etree._Element, pub_id_type: str) -> str | None:
    for element in descendants(root, "article-id"):
        if (element.get("pub-id-type") or "").strip().lower() == pub_id_type:
            value = text_of(element)
            if value:
                return value
    return None


def _doi(root: etree._Element) -> str | None:
    doi = _article_id(root, "doi")
    if doi:
        return doi.replace("doi:", "").strip()
    # Some archives only expose the DOI as an <ext-link>.
    for element in descendants(root, "ext-link"):
        value = text_of(element)
        if value and "10." in value:
            return value.replace("https://doi.org/", "").replace("doi:", "").strip()
    return None


def _journal_meta(root: etree._Element) -> tuple[str | None, str | None, str | None]:
    front = first_descendant(root, "front")
    if front is None:
        return None, None, None
    journal_meta = first_child(front, "journal-meta")
    if journal_meta is None:
        return None, None, None
    journal = _text_at(journal_meta, "journal-title-group", "journal-title")
    if not journal:
        journal = text_of(first_child(journal_meta, "journal-title"))
    issn = None
    for element in descendants(journal_meta, "issn"):
        value = text_of(element)
        if value:
            issn = value
            break
    publisher = text_of(first_descendant(journal_meta, "publisher-name"))
    return journal, issn, publisher


def _pub_date(root: etree._Element, date_type: str) -> str | None:
    for element in descendants(root, "pub-date"):
        if (element.get("pub-type") or element.get("date-type") or "").strip().lower() != (
            date_type.lower()
        ):
            continue
        return _iso_date(element)
    return None


def _iso_date(element: etree._Element) -> str | None:
    year = text_of(first_child(element, "year"))
    if not year:
        return None
    month_text = text_of(first_child(element, "month")) or "1"
    day = text_of(first_child(element, "day")) or "1"
    month = _normalize_month(month_text)
    try:
        return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    except ValueError:
        return year


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalize_month(value: str) -> int:
    text = value.strip().lower()
    if text.isdigit():
        return max(1, min(12, int(text)))
    return _MONTHS.get(text[:3], 1)


# ------------------------------------------------------------------- authors


def _contrib_name(contrib: etree._Element) -> tuple[str | None, str | None, str | None]:
    name = first_child(contrib, "name")
    if name is not None:
        surname = text_of(first_child(name, "surname"))
        given = text_of(first_child(name, "given-names"))
        full = " ".join(part for part in (given, surname) if part) or text_of(name)
        return given, surname, full
    string_name = text_of(first_child(contrib, "string-name"))
    return None, None, string_name


def _authors(root: etree._Element) -> list[Author]:
    result: list[Author] = []
    contrib_group = first_descendant(root, "contrib-group")
    if contrib_group is None:
        return result
    for index, contrib in enumerate(children(contrib_group, "contrib"), start=1):
        if (contrib.get("contrib-type") or "author").lower() not in {
            "author",
            "author-nonpersonal",
        }:
            continue
        given, surname, full = _contrib_name(contrib)
        if not full:
            continue
        affiliation_ids = [
            ref.get("rid")
            for ref in descendants(contrib, "xref")
            if (ref.get("ref-type") or "").lower() == "aff" and ref.get("rid")
        ]
        orcid = None
        for element in descendants(contrib, "contrib-id"):
            if (element.get("contrib-id-type") or "").lower() == "orcid":
                orcid = text_of(element)
        result.append(
            Author(
                given_name=given,
                surname=surname,
                full_name=full,
                email=text_of(first_descendant(contrib, "email")),
                orcid=orcid,
                affiliation_ids=[item for item in affiliation_ids if item],
                sequence=index,
            )
        )
    return result


def _affiliations(root: etree._Element) -> list[Affiliation]:
    result: list[Affiliation] = []
    seen: set[str] = set()
    for element in descendants(root, "aff"):
        identifier = element.get("id")
        if identifier and identifier in seen:
            continue
        # Prefer the institution element; text_of(element) would also append
        # the city and country onto the affiliation name.
        name = (
            text_of(first_child(element, "institution"))
            or text_of(first_child(element, "institution-wrap"))
            or text_of(element)
        )
        if not name:
            continue
        if identifier:
            seen.add(identifier)
        result.append(
            Affiliation(
                id=identifier,
                name=name,
                city=text_of(first_child(element, "city")),
                country=text_of(first_child(element, "country")),
                raw=name,
            )
        )
    return result


# -------------------------------------------------------------------- abstract


def _abstract(root: etree._Element) -> str | None:
    article_meta = first_descendant(root, "article-meta")
    scope = article_meta if article_meta is not None else root
    abstract = first_child(scope, "abstract")
    if abstract is None:
        return None
    return text_of(abstract)


def _keywords(root: etree._Element) -> list[str]:
    seen: list[str] = []
    for group in descendants(root, "kwd-group"):
        for element in children(group, "kwd"):
            value = text_of(element)
            if value and value not in seen:
                seen.append(value)
    return seen


def _open_access(root: etree._Element) -> OpenAccessMetadata:
    license_element = first_descendant(root, "license")
    license_text = None
    if license_element is not None:
        license_text = (
            license_element.get("license-type")
            or text_of(first_child(license_element, "license-p"))
            or text_of(license_element)
        )
    return OpenAccessMetadata(
        is_open_access=True if license_element is not None else None,
        type=license_element.get("license-type") if license_element is not None else None,
        license=license_text,
    )


# -------------------------------------------------------------------- content


def _paragraphs(element: etree._Element) -> list[Paragraph]:
    result: list[Paragraph] = []
    for index, paragraph in enumerate(children(element, "p"), start=1):
        value = text_of(paragraph)
        if not value:
            continue
        result.append(
            Paragraph(id=paragraph.get("id") or f"p{index}", text=value, type="paragraph")
        )
    return result


def _sections(root: etree._Element) -> list[Section]:
    body = first_descendant(root, "body")
    if body is None:
        return []

    def convert(section: etree._Element) -> Section:
        title = text_of(first_child(section, "title"))
        paragraphs = _paragraphs(section)
        nested = [convert(child) for child in children(section, "sec")]
        return Section(
            section_id=section.get("id"),
            title=title,
            paragraphs=paragraphs,
            children=nested,
        )

    top_level = [convert(child) for child in children(body, "sec")]
    if top_level:
        return top_level
    # Some records put paragraphs directly under <body> with no <sec> wrapper.
    paragraphs = _paragraphs(body)
    return [Section(title=None, paragraphs=paragraphs)] if paragraphs else []


def _figures(root: etree._Element) -> list[Figure]:
    result: list[Figure] = []
    for element in descendants(root, "fig"):
        label = text_of(first_child(element, "label"))
        caption = text_of(first_child(element, "caption"))
        images: list[dict[str, Any]] = []
        for graphic in descendants(element, "graphic"):
            href = graphic.get("{http://www.w3.org/1999/xlink}href") or graphic.get("href")
            if href:
                images.append({"url": href})
        result.append(
            Figure(id=element.get("id"), label=label, caption=caption, images=images)
        )
    return result


def _tables(root: etree._Element) -> list[Table]:
    result: list[Table] = []
    for element in descendants(root, "table-wrap"):
        label = text_of(first_child(element, "label"))
        caption = text_of(first_child(element, "caption"))
        rows: list[list[str]] = []
        for row in descendants(element, "tr"):
            cells = [
                text_of(cell) or ""
                for cell in row
                if isinstance(cell.tag, str)
                and local_name(cell) in {"td", "th"}
            ]
            if cells:
                rows.append(cells)
        result.append(Table(id=element.get("id"), label=label, caption=caption, rows=rows))
    return result


def _equations(root: etree._Element) -> list[Equation]:
    result: list[Equation] = []
    for element in descendants(root, "disp-formula"):
        mathml = None
        for child in element.iter():
            if isinstance(child.tag, str) and local_name(child) == "math":
                mathml = etree.tostring(child, encoding="unicode")
                break
        result.append(
            Equation(
                id=element.get("id"),
                label=text_of(first_child(element, "label")),
                mathml=mathml,
                text=text_of(element),
            )
        )
    return result


def _reference(element: etree._Element) -> Reference:
    doi = None
    for item in descendants(element, "pub-id"):
        if (item.get("pub-id-type") or "").lower() == "doi":
            doi = text_of(item)
    authors = [
        text_of(name)
        for name in descendants(element, "name")
        if text_of(name)
    ]
    return Reference(
        id=element.get("id"),
        label=text_of(first_child(element, "label")),
        doi=doi,
        source_text=text_of(first_child(element, "mixed-citation"))
        or text_of(first_child(element, "element-citation")),
        authors=[name for name in authors if name],
        title=_text_at(element, "article-title"),
        journal=_text_at(element, "source"),
        year=text_of(first_child(element, "year")),
    )


def _references(root: etree._Element) -> list[Reference]:
    ref_list = first_descendant(root, "ref-list")
    if ref_list is None:
        return []
    return [_reference(item) for item in children(ref_list, "ref")]


class JatsXmlParser:
    """JATS/NLM article XML, used by PMC, Europe PMC, and many publishers."""

    name = "jats"
    version = PARSER_VERSION
    formats: tuple[str, ...] = ("xml",)

    def sniff(self, content: bytes, *, format: str) -> bool:
        if format != "xml":
            return False
        head = content.lstrip()[:6000].lower()
        if b"<article" not in head:
            return False
        # JATS advertises its DTD, but namespace/local-name shape is the real
        # signal; require at least one JATS-specific element to avoid claiming
        # other <article> XML such as ScienceDirect's.
        jats_markers = (b"jats", b"article-meta", b"pub-id-type", b"contrib-group")
        return any(marker in head for marker in jats_markers)

    def parse(self, content: bytes, context: ParseContext) -> PaperDocument:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        root = etree.fromstring(content, parser=parser)
        journal, issn, publisher = _journal_meta(root)
        return PaperDocument(
            identifiers=DocumentIdentifiers(
                doi=_doi(root),
                pmid=_article_id(root, "pmid") or _article_id(root, "pmcid"),
                publisher_specific={
                    key: value
                    for key, value in (
                        ("pmcid", _article_id(root, "pmcid")),
                        ("pmid", _article_id(root, "pmid")),
                        ("article-id", _article_id(root, "publisher-id")),
                    )
                    if value
                },
            ),
            bibliographic=BibliographicMetadata(
                title=_text_at(root, "front", "article-meta", "title-group", "article-title")
                or text_of(first_descendant(root, "article-title")),
                journal=journal,
                issn=issn,
                volume=_text_at(root, "front", "article-meta", "volume"),
                issue=_text_at(root, "front", "article-meta", "issue"),
                article_number=_article_id(root, "elocation-id"),
                document_type=root.get("article-type"),
                publisher=publisher,
            ),
            dates=PublicationDates(
                received=_pub_date(root, "received"),
                revised=_pub_date(root, "revised"),
                accepted=_pub_date(root, "accepted"),
                online=_pub_date(root, "epub") or _pub_date(root, "online"),
                version_of_record=_pub_date(root, "pub"),
                cover=None,
                indexed=None,
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
                provider=context.provider or "jats",
                service=context.service or "fulltext",
                format="xml",
                source_path=context.source_path,
                parser_version=self.version,
                acquired_at=datetime.now(UTC),
                credential_label=context.credential_label,
                http_status=context.http_status,
                sha256=sha256(content).hexdigest(),
            ),
        )
