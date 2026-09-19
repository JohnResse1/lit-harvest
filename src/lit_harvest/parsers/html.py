"""Deterministic HTML full-text parser.

Many open-access copies are served as HTML rather than XML. This parser reads
the standard scholarly markup conventions (Dublin Core / citation meta tags,
``<article>``, headings, and paragraphs) using lxml's HTML parser. It is
deliberately conservative: when it cannot find structured article content it
produces whatever headings and paragraphs exist instead of guessing, so the
caller can still see that the payload was thin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from lxml import etree, html
from lxml.html import HtmlElement

from lit_harvest.models import (
    Author,
    BibliographicMetadata,
    DocumentIdentifiers,
    DocumentProvenance,
    Figure,
    OpenAccessMetadata,
    PaperDocument,
    Paragraph,
    Reference,
    Section,
)
from lit_harvest.parsers.base import ParseContext

PARSER_VERSION = "html-fulltext/1.0"

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "form", "aside", "noscript"}


def _text_content(element: Any) -> str | None:
    """`text_content` exists on lxml HTML elements, not on the base type."""
    if isinstance(element, HtmlElement):
        return str(element.text_content())
    return str("".join(element.itertext())) or None


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


def _meta_map(root: etree._Element) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for element in root.iter("meta"):
        name = (element.get("name") or element.get("property") or "").strip().lower()
        content = _clean(element.get("content"))
        if name and content:
            result.setdefault(name, []).append(content)
    return result


def _first(meta: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        values = meta.get(key.lower())
        if values:
            return values[0]
    return None


def _authors(meta: dict[str, list[str]], root: etree._Element) -> list[Author]:
    names = meta.get("citation_author") or meta.get("dc.creator") or []
    authors = [
        Author(full_name=name, sequence=index)
        for index, name in enumerate(names, start=1)
        if name
    ]
    if authors:
        return authors
    # Fall back to a single JSON-LD author list when present.
    for element in root.iter("script"):
        if (element.get("type") or "").lower() != "application/ld+json":
            continue
        text = _clean(element.text)
        if not text or '"author"' not in text:
            continue
        import json

        try:
            payload = json.loads(text)
        except ValueError:
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_authors = entry.get("author")
            if isinstance(raw_authors, dict):
                raw_authors = [raw_authors]
            if not isinstance(raw_authors, list):
                continue
            for index, item in enumerate(raw_authors, start=1):
                if isinstance(item, dict) and _clean(item.get("name")):
                    authors.append(Author(full_name=item["name"], sequence=index))
                elif isinstance(item, str):
                    authors.append(Author(full_name=item, sequence=index))
            if authors:
                return authors
    return authors


def _body(root: etree._Element) -> etree._Element:
    """The most article-specific container available, else the whole tree."""
    for tag in ("article", "main", "body"):
        for element in root.iter(tag):
            return element
    return root


def _sections(body: etree._Element) -> list[Section]:
    sections: list[Section] = []
    current = Section(title=None, paragraphs=[])
    found_heading = False
    for element in body.iter():
        if not isinstance(element.tag, str):
            continue
        tag = element.tag.lower()
        if tag in _SKIP_TAGS:
            continue
        if tag in _HEADING_TAGS:
            title = _clean(_text_content(element))
            if not title:
                continue
            if current.paragraphs or found_heading or current.title:
                sections.append(current)
            current = Section(title=title, paragraphs=[])
            found_heading = True
        elif tag == "p":
            text = _clean(_text_content(element))
            if text and len(text) > 1:
                current.paragraphs.append(
                    Paragraph(id=element.get("id"), text=text, type="paragraph")
                )
    if current.paragraphs or current.title:
        sections.append(current)
    return [section for section in sections if section.paragraphs or section.title]


def _figures(body: etree._Element) -> list[Figure]:
    figures: list[Figure] = []
    for element in body.iter("figure"):
        caption = None
        for child in element.iter("figcaption"):
            caption = _clean(_text_content(child))
            if caption:
                break
        images: list[dict[str, Any]] = []
        for image in element.iter("img"):
            source = image.get("src")
            if source:
                images.append({"url": source, "alt": _clean(image.get("alt"))})
        figures.append(Figure(id=element.get("id"), caption=caption, images=images))
    return figures


def _abstract(meta: dict[str, list[str]], body: etree._Element) -> str | None:
    value = _first(meta, "citation_abstract", "dc.description", "description")
    if value:
        return value
    for element in body.iter():
        if not isinstance(element.tag, str):
            continue
        classes = (element.get("class") or "").lower()
        identifier = (element.get("id") or "").lower()
        if "abstract" not in classes and "abstract" not in identifier:
            continue
        text = _clean(_text_content(element))
        if text:
            return text
    return None


class HtmlFullTextParser:
    """Publisher or repository HTML that follows scholarly markup conventions."""

    name = "html_fulltext"
    version = PARSER_VERSION
    formats: tuple[str, ...] = ("html",)

    # HTML is the universal fallback, so this parser always claims the format;
    # it sits last in registration order behind more specific parsers.
    def sniff(self, content: bytes, *, format: str) -> bool:
        if format != "html":
            return False
        head = content.lstrip()[:2000].lower()
        return b"<html" in head or b"<!doctype html" in head or b"<article" in head

    def parse(self, content: bytes, context: ParseContext) -> PaperDocument:
        parser = html.HTMLParser(encoding="utf-8", recover=True)
        root = html.fromstring(content, parser=parser)
        meta = _meta_map(root)
        body = _body(root)
        keywords_raw = _first(meta, "citation_keywords", "keywords")
        keywords = (
            [item.strip() for item in keywords_raw.split(",") if item.strip()]
            if keywords_raw
            else []
        )
        references: list[Reference] = []
        return PaperDocument(
            identifiers=DocumentIdentifiers(
                doi=_first(meta, "citation_doi", "dc.identifier"),
            ),
            bibliographic=BibliographicMetadata(
                title=_first(meta, "citation_title", "dc.title", "og:title")
                or _clean(root.findtext(".//title")),
                journal=_first(meta, "citation_journal_title", "dc.source"),
                issn=_first(meta, "citation_issn"),
                volume=_first(meta, "citation_volume"),
                issue=_first(meta, "citation_issue"),
                article_number=_first(meta, "citation_firstpage"),
                document_type=_first(meta, "citation_article_type", "dc.type"),
                publisher=_first(meta, "citation_publisher", "dc.publisher"),
            ),
            authors=_authors(meta, root),
            abstract=_abstract(meta, body),
            keywords=keywords,
            open_access=OpenAccessMetadata(is_open_access=None),
            sections=_sections(body),
            figures=_figures(body),
            references=references,
            provenance=DocumentProvenance(
                provider=context.provider or "html",
                service=context.service or "fulltext",
                format="html",
                source_path=context.source_path,
                parser_version=self.version,
                acquired_at=datetime.now(UTC),
                credential_label=context.credential_label,
                http_status=context.http_status,
                sha256=sha256(content).hexdigest(),
            ),
        )
