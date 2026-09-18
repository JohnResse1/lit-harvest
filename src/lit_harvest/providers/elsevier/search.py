"""Deterministic parsing of Scopus Search STANDARD JSON responses."""

from __future__ import annotations

from typing import Any

from lit_harvest.models import PaperCreate, PaperIdentifiers


def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _entry(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("search-results", {}).get("entry", [])
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _affiliation_text(entry: dict[str, Any]) -> str | None:
    affiliations = entry.get("affiliation")
    if isinstance(affiliations, list):
        names = []
        for affiliation in affiliations:
            if isinstance(affiliation, dict):
                name = _string(affiliation.get("affilname"))
                if name:
                    names.append(name)
        return "; ".join(dict.fromkeys(names)) or None
    if isinstance(affiliations, dict):
        return _string(affiliations.get("affilname"))
    return None


def parse_search_response(payload: dict[str, Any]) -> tuple[list[PaperCreate], dict[str, Any]]:
    results = payload.get("search-results", {})
    if not isinstance(results, dict):
        return [], {}
    entries = results.get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        entries = []

    papers: list[PaperCreate] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        doi_value = _string(item.get("prism:doi") or item.get("doi"))
        scopus_id = _string(
            item.get("dc:identifier", "").replace("SCOPUS_ID:", "")
            if _string(item.get("dc:identifier"))
            else None
        )
        eid = _string(item.get("eid"))
        if not any((doi_value, scopus_id, eid)):
            continue
        extra: dict[str, Any] = {}
        stable_fields = (
            "prism:issn",
            "prism:eIssn",
            "prism:volume",
            "prism:issueIdentifier",
            "prism:pageRange",
            "prism:coverDate",
            "prism:coverDisplayDate",
            "prism:publicationName",
            "prism:aggregationType",
            "prism:url",
            "citedby-count",
            "openaccess",
            "openaccessFlag",
            "freetoread",
            "freetoreadLabel",
            "subtype",
            "subtypeDescription",
            "source-id",
            "article-number",
            "author",
            "affiliation",
        )
        for field in stable_fields:
            if field in item:
                extra[field] = item[field]
        affiliation = _affiliation_text(item)
        if affiliation:
            extra["affiliation_text"] = affiliation
        creator = _string(item.get("dc:creator") or item.get("creator"))
        publisher = _string(item.get("prism:publisher"))
        cover_date = _string(item.get("prism:coverDate"))
        publication_year = _integer(cover_date[:4]) if cover_date else None
        paper = PaperCreate(
            doi=doi_value,
            title=_string(item.get("dc:title")),
            journal=_string(item.get("prism:publicationName")),
            publication_year=publication_year,
            publisher=publisher,
            document_type=_string(
                item.get("subtypeDescription") or item.get("prism:aggregationType")
            ),
            discovery_source="scopus_search",
            identifiers=PaperIdentifiers(
                doi=doi_value,
                scopus_id=scopus_id,
                eid=eid,
            ),
            extra={
                "creator": creator,
                "citation_count": _integer(item.get("citedby-count")),
                "open_access": item.get("openaccess") or item.get("openaccessFlag"),
                "scopus_url": _string(item.get("prism:url") or item.get("link")),
                **extra,
            },
        )
        papers.append(paper)

    info = {
        "total_results": _integer(results.get("opensearch:totalResults")),
        "start_index": _integer(results.get("opensearch:startIndex")) or 1,
        "items_per_page": _integer(results.get("opensearch:itemsPerPage")) or len(papers),
        "current_cursor": _string(
            results.get("cursor", {}).get("@current")
            if isinstance(results.get("cursor"), dict)
            else None
        ),
        "next_cursor": _string(
            results.get("cursor", {}).get("@next")
            if isinstance(results.get("cursor"), dict)
            else None
        ),
    }
    return papers, info
