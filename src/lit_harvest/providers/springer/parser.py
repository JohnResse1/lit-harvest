"""Deterministic parsing of Springer Nature API records.

The Meta API and OpenAccess API share the same record shape, so one parser
serves both. Differences that matter:

* `abstract` is usually a string, but the OpenAccess API may return a mapping
  like ``{"h1": "Highlights", "p": "..."}``.
* `url` is a list of ``{"format", "platform", "value"}`` entries; only the
  `pdf`/`html` entries are actionable.
"""

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


def flatten_abstract(value: Any) -> str | None:
    """Springer sometimes returns a structured abstract as a nested mapping."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        collected = [flatten_abstract(item) for item in value]
        joined = " ".join(part for part in collected if part)
        return joined or None
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            text = flatten_abstract(item)
            if not text:
                continue
            if key.lower().startswith("h") and len(key) <= 3:
                # Heading keys such as h1/h2 label a subsection.
                parts.append(f"{text}:")
            else:
                parts.append(text)
        joined = " ".join(parts)
        return joined or None
    return _string(value)


def extract_urls(record: dict[str, Any]) -> dict[str, str | None]:
    """Pull the PDF and HTML targets out of a Springer `url` list."""
    result: dict[str, str | None] = {"pdf": None, "html": None, "landing": None}
    entries = record.get("url")
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        fmt = str(entry.get("format") or "").strip().lower()
        if fmt == "pdf" and result["pdf"] is None:
            result["pdf"] = value
        elif fmt == "html" and result["html"] is None:
            result["html"] = value
        elif not fmt and result["landing"] is None:
            result["landing"] = value
    return result


def _creators(record: dict[str, Any]) -> list[dict[str, str | None]]:
    people: list[dict[str, str | None]] = []
    creators = record.get("creators")
    if not isinstance(creators, list):
        return people
    for item in creators:
        if isinstance(item, dict):
            name = _string(item.get("creator"))
            orcid = _string(item.get("ORCID") or item.get("orcid"))
        else:
            name, orcid = _string(item), None
        if name:
            people.append({"name": name, "orcid": orcid})
    return people


def _open_access(record: dict[str, Any]) -> bool | None:
    # Meta API uses `openaccess`, OpenAccess API uses `openAccess`.
    raw = record.get("openaccess")
    if raw is None:
        raw = record.get("openAccess")
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"true", "1", "yes"}


def parse_springer_record(record: dict[str, Any]) -> PaperCreate:
    doi = _string(record.get("doi"))
    identifier = _string(record.get("identifier"))
    if doi and identifier and identifier.lower().startswith("doi:"):
        doi = doi or identifier[4:]
    urls = extract_urls(record)
    creators = _creators(record)
    is_oa = _open_access(record)
    publication_date = _string(record.get("publicationDate") or record.get("coverDate"))
    year = _integer(publication_date[:4]) if publication_date else None

    keywords: list[str] = []
    for key in ("keyword", "subjects", "disciplines"):
        raw = record.get(key)
        if isinstance(raw, list):
            for item in raw:
                text = (
                    item
                    if isinstance(item, str)
                    else _string(item.get("name") if isinstance(item, dict) else item)
                )
                if text and text not in keywords:
                    keywords.append(text)

    return PaperCreate(
        doi=doi,
        title=_string(record.get("title")),
        journal=_string(record.get("publicationName")),
        publication_year=year,
        publisher=_string(record.get("publisherName") or record.get("publisher")),
        document_type=_string(record.get("contentType") or record.get("genre")),
        discovery_source="springer",
        identifiers=PaperIdentifiers(doi=doi),
        extra={
            "springer_identifier": identifier,
            "abstract": flatten_abstract(record.get("abstract")),
            "authors": creators,
            "author_count": len(creators),
            "keywords": keywords,
            "open_access": {
                "is_oa": is_oa,
                "oa_status": "open" if is_oa else None,
                # A publisher-hosted PDF is a legitimate OA download target.
                "pdf_url": urls["pdf"] if is_oa else None,
                "oa_url": urls["html"] or urls["landing"],
            },
            "springer_urls": urls,
            "issn": _string(record.get("issn") or record.get("eIssn")),
            "volume": _string(record.get("volume")),
            "issue": _string(record.get("number")),
            "first_page": _string(record.get("startingPage")),
            "last_page": _string(record.get("endingPage")),
            "language": _string(record.get("language")),
        },
    )


def parse_springer_response(payload: dict[str, Any]) -> tuple[list[PaperCreate], dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    papers = [parse_springer_record(item) for item in records if isinstance(item, dict)]

    result = payload.get("result")
    total = start = page_length = None
    if isinstance(result, list) and result and isinstance(result[0], dict):
        first = result[0]
        total = _integer(first.get("total"))
        start = _integer(first.get("start"))
        page_length = _integer(first.get("pageLength"))
    return papers, {"total_results": total, "start": start, "page_length": page_length}
