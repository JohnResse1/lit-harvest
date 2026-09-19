"""Deterministic parsing of Europe PMC search records.

Europe PMC indexes life-science literature and exposes open-access full text as
JATS XML. The search payload is JSON, so this module only reads metadata fields;
full text is downloaded separately and parsed by the JATS parser.
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


def _authors(entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw = entry.get("authorList")
    authors: list[dict[str, Any]] = []
    if not isinstance(raw, dict):
        return authors
    for index, item in enumerate(raw.get("author") or [], start=1):
        if not isinstance(item, dict):
            continue
        name = _string(item.get("fullName"))
        if not name:
            name = " ".join(
                part
                for part in (
                    _string(item.get("firstName")),
                    _string(item.get("lastName")),
                )
                if part
            )
        if not name:
            continue
        orcid = _string(item.get("authorId"))
        authors.append(
            {
                "name": name,
                "orcid": orcid if item.get("authorIdType") == "ORCID" else None,
                "sequence": index,
            }
        )
    return authors


def parse_europepmc_record(entry: dict[str, Any]) -> PaperCreate:
    doi = (_string(entry.get("doi")) or "").lower() or None
    pmcid = _string(entry.get("pmcid"))
    pmid = _string(entry.get("pmid"))
    journal = entry.get("journalInfo")
    journal = journal if isinstance(journal, dict) else {}
    journal_title = _string(journal.get("journal", {}).get("title")) if isinstance(
        journal.get("journal"), dict
    ) else None
    year = _integer(entry.get("pubYear"))
    is_oa = (_string(entry.get("isOpenAccess")) or "").upper() == "Y"
    has_fulltext = (_string(entry.get("hasTextMinedTerms")) or "").upper() == "Y" or bool(pmcid)

    return PaperCreate(
        doi=doi,
        title=_string(entry.get("title")),
        journal=journal_title,
        publication_year=year,
        publisher=None,
        document_type=_string(entry.get("pubType")),
        discovery_source="europepmc",
        identifiers=PaperIdentifiers(doi=doi, pmid=pmid, pmcid=pmcid),
        extra={
            "abstract": entry.get("abstractText"),
            "authors": _authors(entry),
            "author_count": _integer(entry.get("authorCount")) or len(_authors(entry)),
            "pmcid": pmcid,
            "pmid": pmid,
            "is_oa": is_oa,
            "has_fulltext": has_fulltext,
            "journal": journal_title,
            "volume": _string(journal.get("volume")),
            "issue": _string(journal.get("issue")),
            "pages": _string(entry.get("pageInfo")),
            # Europe PMC serves OA full text as JATS once a PMCID exists.
            "open_access": {
                "is_oa": is_oa,
                "oa_status": "open" if is_oa else None,
                "pdf_url": None,
            },
            "source": _string(entry.get("source")),
            "europepmc_id": _string(entry.get("id")),
        },
    )


def parse_search_response(payload: dict[str, Any]) -> tuple[list[PaperCreate], dict[str, Any]]:
    result_list = payload.get("resultList")
    result_list = result_list if isinstance(result_list, dict) else {}
    results = result_list.get("result")
    results = results if isinstance(results, list) else []
    papers = [parse_europepmc_record(item) for item in results if isinstance(item, dict)]
    info = {
        "total_results": _integer(payload.get("hitCount")),
        "next_cursor": _string(payload.get("nextCursorMark")),
    }
    return papers, info
