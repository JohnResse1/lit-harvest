"""Load, normalize, validate, and deduplicate DOI lists from common formats."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lit_harvest.storage.files import normalize_doi

_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_WRAPPERS = " \t\r\n\"'[](){}<>"


@dataclass(slots=True)
class DOIItem:
    doi: str
    raw: str
    source_row: int | None = None


@dataclass(slots=True)
class DOIValidationError:
    raw: str
    source_row: int | None
    reason: str


@dataclass(slots=True)
class DOIList:
    valid: list[DOIItem] = field(default_factory=list)
    invalid: list[DOIValidationError] = field(default_factory=list)


def _clean(value: str) -> str:
    value = value.strip(_WRAPPERS)
    value = normalize_doi(value)
    return value.rstrip(".,;)]}")


def validate_doi(value: str) -> tuple[bool, str]:
    normalized = _clean(value)
    if not normalized:
        return False, "empty value"
    if not _DOI_PATTERN.match(normalized):
        return False, "invalid DOI shape"
    if len(normalized) > 512:
        return False, "DOI exceeds 512 characters"
    return True, normalized


def _iter_values(path: Path, doi_column: str) -> list[tuple[str, int | None]]:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".tsv", ".txt", ".json", ".jsonl"}:
        raise ValueError(f"Unsupported DOI file type: {suffix}")
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if reader.fieldnames is None:
                return []
            columns = {name.strip().lower(): name for name in reader.fieldnames}
            if doi_column.lower() not in columns:
                raise ValueError(
                    f"Column {doi_column!r} not found. Available columns: {reader.fieldnames}"
                )
            actual = columns[doi_column.lower()]
            return [
                (row.get(actual, ""), index + 2)
                for index, row in enumerate(reader)
                if row.get(actual) is not None
            ]
    if suffix == ".txt":
        return [
            (line, index + 1)
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines())
            if line.strip()
        ]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [
                (_extract_json_value(item, doi_column), index + 1)
                for index, item in enumerate(payload)
            ]
        if isinstance(payload, dict):
            for key in (doi_column, "dois", "items", "papers"):
                if key in payload:
                    value = payload[key]
                    if isinstance(value, list):
                        return [
                            (_extract_json_value(item, doi_column), index + 1)
                            for index, item in enumerate(value)
                        ]
            return [(_extract_json_value(payload, doi_column), 1)]
        return [(str(payload), 1)]
    items: list[tuple[str, int | None]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            items.append((line, index + 1))
            continue
        items.append((_extract_json_value(payload, doi_column), index + 1))
    return items


def _extract_json_value(value: Any, key: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if key in value:
            return str(value[key])
        for candidate in ("doi", "DOI", "Doi"):
            if candidate in value:
                return str(value[candidate])
    return ""


def load_dois(path: str | Path, *, doi_column: str = "doi") -> DOIList:
    source = Path(path)
    result = DOIList()
    seen: set[str] = set()
    for raw, row in _iter_values(source, doi_column):
        ok, normalized_or_reason = validate_doi(raw)
        if not ok:
            result.invalid.append(
                DOIValidationError(raw=raw, source_row=row, reason=normalized_or_reason)
            )
            continue
        if normalized_or_reason in seen:
            continue
        seen.add(normalized_or_reason)
        result.valid.append(DOIItem(doi=normalized_or_reason, raw=raw, source_row=row))
    return result


def load_single_doi(value: str) -> str:
    ok, normalized_or_reason = validate_doi(value)
    if not ok:
        raise ValueError(normalized_or_reason)
    return normalized_or_reason
