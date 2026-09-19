"""Deterministic parsing of Crossref REST API work records.

Crossref is the authoritative DOI registration agency. Beyond bibliographic
metadata it publishes each publisher's registered **text-mining links**
(``link[]`` entries with ``intended-application: text-mining``). Those links are
how many publishers expose a machine-readable full-text route without a
bespoke per-publisher API, so Crossref doubles as a TDM discovery layer.

Metadata is licensed CC0; the TDM links merely *point* at content that still
requires the caller's own entitlement.
"""

from __future__ import annotations

from typing import Any

from lit_harvest.models import PaperCreate, PaperIdentifiers

#: Crossref `link[].intended-application` values that indicate a TDM route.
TDM_APPLICATIONS = {"text-mining", "text-mining-and-similar"}


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list) and value:
        return _string(value[0])
    return None


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_list(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return _string(value[0])
    return _string(value)


def _date_parts(message: dict[str, Any]) -> tuple[int | None, str | None]:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        entry = message.get(key)
        if not isinstance(entry, dict):
            continue
        parts = entry.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = _integer(parts[0][0])
            month = _integer(parts[0][1]) if len(parts[0]) > 1 else None
            day = _integer(parts[0][2]) if len(parts[0]) > 2 else None
            iso = None
            if year:
                iso = f"{year:04d}-{month or 1:02d}-{day or 1:02d}"
            return year, iso
    return None, None


def _authors(message: dict[str, Any]) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    for index, author in enumerate(message.get("author") or [], start=1):
        if not isinstance(author, dict):
            continue
        given = _string(author.get("given"))
        family = _string(author.get("family"))
        name = _string(author.get("name")) or " ".join(
            part for part in (given, family) if part
        )
        if not name:
            continue
        affiliations = [
            _string(item.get("name"))
            for item in (author.get("affiliation") or [])
            if isinstance(item, dict) and _string(item.get("name"))
        ]
        people.append(
            {
                "name": name,
                "given": given,
                "family": family,
                "orcid": _string(author.get("ORCID")),
                "sequence": index,
                "affiliations": affiliations,
            }
        )
    return people


def extract_tdm_links(message: dict[str, Any]) -> list[dict[str, str]]:
    """Pull publisher-registered text-mining links out of a work record.

    Only links the publisher explicitly tagged for text mining are returned;
    ordinary landing-page links are ignored.
    """
    links: list[dict[str, str]] = []
    for entry in message.get("link") or []:
        if not isinstance(entry, dict):
            continue
        application = (_string(entry.get("intended-application")) or "").lower()
        if application not in TDM_APPLICATIONS:
            continue
        url = _string(entry.get("URL"))
        if not url:
            continue
        links.append(
            {
                "url": url,
                "content_type": _string(entry.get("content-type")) or "",
                "content_version": _string(entry.get("content-version")) or "",
            }
        )
    return links


def parse_crossref_record(message: dict[str, Any]) -> PaperCreate:
    doi = (_string(message.get("DOI")) or "").lower() or None
    year, iso_date = _date_parts(message)
    authors = _authors(message)
    container = _string(message.get("container-title"))
    short_container = _string(message.get("short-container-title"))
    tdm_links = extract_tdm_links(message)
    license_entries = [
        {
            "url": _string(item.get("URL")),
            "content_version": _string(item.get("content-version")),
        }
        for item in (message.get("license") or [])
        if isinstance(item, dict) and _string(item.get("URL"))
    ]
    return PaperCreate(
        doi=doi,
        title=_first_list(message.get("title")),
        journal=container or short_container,
        publication_year=year,
        publisher=_string(message.get("publisher")),
        document_type=_string(message.get("type")),
        discovery_source="crossref",
        identifiers=PaperIdentifiers(doi=doi),
        extra={
            "crossref_type": _string(message.get("type")),
            "abstract": message.get("abstract"),
            "authors": authors,
            "author_count": len(authors),
            "published": iso_date,
            "issn": message.get("ISSN") or [],
            "volume": _string(message.get("volume")),
            "issue": _string(message.get("issue")),
            "page": _string(message.get("page")),
            "article_number": _string(message.get("article-number")),
            "reference_count": _integer(message.get("reference-count")),
            "is_referenced_by_count": _integer(message.get("is-referenced-by-count")),
            "subject": message.get("subject") or [],
            # Publisher-registered machine-readable routes; entitlement still
            # applies when they are followed.
            "tdm_links": tdm_links,
            "licenses": license_entries,
            "url": _string(message.get("URL")),
        },
    )


def parse_search_response(payload: dict[str, Any]) -> tuple[list[PaperCreate], dict[str, Any]]:
    message = payload.get("message")
    message = message if isinstance(message, dict) else {}
    items = message.get("items")
    items = items if isinstance(items, list) else []
    papers = [parse_crossref_record(item) for item in items if isinstance(item, dict)]
    info = {
        "total_results": _integer(message.get("total-results")),
        "items_per_page": _integer(message.get("items-per-page")),
    }
    return papers, info
