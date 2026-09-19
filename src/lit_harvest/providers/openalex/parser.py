"""Deterministic parsing of OpenAlex work records.

OpenAlex publishes CC0 metadata covering essentially every publisher, which
makes it the practical cross-publisher discovery layer. It is metadata only:
no full text is served here, but abstracts and complete author lists are.
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


def strip_openalex_id(value: str | None) -> str | None:
    """`https://openalex.org/W123` -> `W123`."""
    if not value:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1] or None


def strip_doi(value: str | None) -> str | None:
    """`https://doi.org/10.1/x` -> `10.1/x`."""
    if not value:
        return None
    lowered = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if lowered.lower().startswith(prefix):
            return lowered[len(prefix) :]
    return lowered


def reconstruct_abstract(inverted: Any) -> str | None:
    """Rebuild readable text from OpenAlex's `abstract_inverted_index`.

    The index maps each word to the positions where it occurs, which keeps the
    payload small while remaining lossless.
    """
    if not isinstance(inverted, dict):
        return None
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        if not isinstance(word, str) or not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions[index] = word
    if not positions:
        return None
    return " ".join(positions[key] for key in sorted(positions))


def _authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []
    for position, authorship in enumerate(work.get("authorships") or [], start=1):
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        name = _string(author.get("display_name"))
        if not name:
            continue
        institutions = [
            _string(item.get("display_name"))
            for item in (authorship.get("institutions") or [])
            if isinstance(item, dict) and _string(item.get("display_name"))
        ]
        # OpenAlex returns countries as plain strings (and sometimes objects).
        countries: list[str] = []
        for element in authorship.get("countries") or []:
            if isinstance(element, str):
                countries.append(element)
            elif isinstance(element, dict):
                code = _string(element.get("country_code"))
                if code:
                    countries.append(code)
        authors.append(
            {
                "name": name,
                "orcid": _string(author.get("orcid")),
                "position": position,
                "institutions": institutions,
                "countries": countries,
            }
        )
    return authors


def _location(work: dict[str, Any]) -> dict[str, Any]:
    """`primary_location` may be null, a dict, or missing."""
    location = work.get("primary_location")
    return location if isinstance(location, dict) else {}


def _source(work: dict[str, Any]) -> dict[str, Any]:
    source = _location(work).get("source")
    return source if isinstance(source, dict) else {}


def _journal(work: dict[str, Any]) -> tuple[str | None, str | None]:
    source = _source(work)
    return _string(source.get("display_name")), _string(source.get("issn_l"))


def _open_access(work: dict[str, Any]) -> dict[str, Any]:
    oa = work.get("open_access")
    oa = oa if isinstance(oa, dict) else {}
    best = work.get("best_oa_location")
    best = best if isinstance(best, dict) else {}
    return {
        "is_oa": oa.get("is_oa") if isinstance(oa, dict) else None,
        "oa_status": oa.get("oa_status") if isinstance(oa, dict) else None,
        "oa_url": oa.get("oa_url") if isinstance(oa, dict) else None,
        "pdf_url": best.get("pdf_url") if isinstance(best, dict) else None,
        "license": best.get("license") if isinstance(best, dict) else None,
        "version": best.get("version") if isinstance(best, dict) else None,
    }


def parse_work(work: dict[str, Any]) -> PaperCreate:
    """Convert one OpenAlex work into the shared PaperCreate model."""
    doi = strip_doi(_string(work.get("doi")))
    openalex_id = strip_openalex_id(_string(work.get("id")))
    journal, issn = _journal(work)
    biblio = work.get("biblio") or {}
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    authors = _authors(work)

    identifiers = PaperIdentifiers(doi=doi, openalex_id=openalex_id)
    if issn:
        identifiers.publisher_specific["issn"] = issn

    return PaperCreate(
        doi=doi,
        title=_string(work.get("title")) or _string(work.get("display_name")),
        journal=journal,
        publication_year=_integer(work.get("publication_year")),
        publisher=_string(_source(work).get("host_organization_name")),
        document_type=_string(work.get("type")),
        discovery_source="openalex",
        identifiers=identifiers,
        extra={
            "openalex_id": openalex_id,
            "openalex_url": _string(work.get("id")),
            "abstract": abstract,
            "authors": authors,
            "author_count": len(authors),
            "citation_count": _integer(work.get("cited_by_count")),
            "open_access": _open_access(work),
            "issn": issn,
            "volume": _string(biblio.get("volume")) if isinstance(biblio, dict) else None,
            "issue": _string(biblio.get("issue")) if isinstance(biblio, dict) else None,
            "first_page": _string(biblio.get("first_page")) if isinstance(biblio, dict) else None,
            "last_page": _string(biblio.get("last_page")) if isinstance(biblio, dict) else None,
            "referenced_works_count": len(work.get("referenced_works") or []),
            "concepts": [
                _string(item.get("display_name"))
                for item in (work.get("concepts") or [])[:10]
                if isinstance(item, dict) and _string(item.get("display_name"))
            ],
            "is_retracted": work.get("is_retracted"),
            "language": _string(work.get("language")),
        },
    )


def parse_search_response(payload: dict[str, Any]) -> tuple[list[PaperCreate], dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        results = []
    papers = [parse_work(item) for item in results if isinstance(item, dict)]
    meta = payload.get("meta") or {}
    info = {
        "total_results": _integer(meta.get("count")) if isinstance(meta, dict) else None,
        "page": _integer(meta.get("page")) if isinstance(meta, dict) else None,
        "per_page": _integer(meta.get("per_page")) if isinstance(meta, dict) else None,
    }
    return papers, info
