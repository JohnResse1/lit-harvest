"""Deterministic parsing of Unpaywall DOI records.

Unpaywall reports every known open-access location for a DOI, including
repository (green) copies. Green copies are especially valuable here because
they are usually free to download and therefore avoid the institutional
subscription quota entirely.
"""

from __future__ import annotations

from typing import Any


#: Location preference: a direct PDF beats a landing page.
def _string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def parse_oa_locations(record: dict[str, Any]) -> list[dict[str, Any]]:
    """All OA locations, best (direct PDF) first."""
    locations: list[dict[str, Any]] = []
    for entry in record.get("oa_locations") or []:
        if not isinstance(entry, dict):
            continue
        locations.append(
            {
                "url": _string(entry.get("url")),
                "url_for_pdf": _string(entry.get("url_for_pdf")),
                "url_for_landing_page": _string(entry.get("url_for_landing_page")),
                "host_type": _string(entry.get("host_type")),
                "version": _string(entry.get("version")),
                "license": _string(entry.get("license")),
                "is_best": bool(entry.get("is_best")),
            }
        )
    locations.sort(key=lambda item: (not bool(item["url_for_pdf"]), not item["is_best"]))
    return locations


def parse_unpaywall_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Unpaywall record into the shared OA-lookup shape."""
    locations = parse_oa_locations(record)
    best = next(
        (item for item in locations if item["url_for_pdf"]),
        locations[0] if locations else None,
    )
    is_oa = bool(record.get("is_oa"))
    return {
        "doi": _string(record.get("doi")),
        "is_oa": is_oa,
        "oa_status": _string(record.get("oa_status")),
        "journal_is_oa": bool(record.get("journal_is_oa")),
        "publisher": _string(record.get("publisher")),
        "title": _string(record.get("title")),
        "year": record.get("year"),
        "license": (best or {}).get("license"),
        "version": (best or {}).get("version"),
        "host_type": (best or {}).get("host_type"),
        "pdf_url": (best or {}).get("url_for_pdf"),
        "landing_url": (best or {}).get("url_for_landing_page") or (best or {}).get("url"),
        # Downloadable only when a direct file URL exists.
        "downloadable": bool((best or {}).get("url_for_pdf")),
        "locations": locations,
        "source": "unpaywall",
    }
