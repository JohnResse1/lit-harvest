"""Reviewable search results.

A search stores candidates instead of immediately downloading them, so the user
can inspect metadata and choose exactly which papers to retrieve.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from lit_harvest.storage.database import Database


@dataclass(slots=True)
class SearchCandidate:
    candidate_id: str
    paper_id: str | None
    doi: str | None
    title: str | None
    journal: str | None
    year: int | None
    authors: str | None
    affiliation: str | None
    document_type: str | None
    citation_count: int | None
    open_access: bool | None
    free_to_read: str | None
    issn: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    cover_date: str | None
    scopus_id: str | None
    eid: str | None
    scopus_url: str | None
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "paper_id": self.paper_id,
            "doi": self.doi,
            "title": self.title,
            "journal": self.journal,
            "year": self.year,
            "authors": self.authors,
            "affiliation": self.affiliation,
            "document_type": self.document_type,
            "citation_count": self.citation_count,
            "open_access": self.open_access,
            "free_to_read": self.free_to_read,
            "issn": self.issn,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "cover_date": self.cover_date,
            "scopus_id": self.scopus_id,
            "eid": self.eid,
            "scopus_url": self.scopus_url,
            "selected": self.selected,
        }


@dataclass(slots=True)
class SearchSession:
    session_id: str
    query: str
    created_at: str
    total_results: int | None
    max_results: int
    candidates: list[SearchCandidate] = field(default_factory=list)
    raw_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "created_at": self.created_at,
            "total_results": self.total_results,
            "max_results": self.max_results,
            "candidate_count": len(self.candidates),
            "selected_count": sum(1 for item in self.candidates if item.selected),
            "raw_paths": self.raw_paths,
            "candidates": [item.to_dict() for item in self.candidates],
        }


def _first_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return None
    if isinstance(value, dict):
        for key in ("$", "value", "@href", "affilname"):
            if key in value:
                text = _first_text(value[key])
                if text:
                    return text
    return None


def _all_authors(value: Any) -> str | None:
    if isinstance(value, dict):
        names = value.get("author")
        if isinstance(names, list):
            collected = []
            for item in names:
                if isinstance(item, dict):
                    name = item.get("authname") or item.get("$")
                    if isinstance(name, str) and name.strip():
                        collected.append(name.strip())
            return "; ".join(collected) or None
    return _first_text(value)


def _affiliations(value: Any) -> str | None:
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("affilname")
                if isinstance(name, str):
                    names.append(name)
        unique = list(dict.fromkeys(names))
        return "; ".join(unique) or None
    return _first_text(value)


class SearchSessionStore:
    """In-memory preview sessions, persisted to disk as JSON when needed."""

    def __init__(self, database: Database):
        self.database = database
        self._sessions: dict[str, SearchSession] = {}

    def create(
        self,
        *,
        query: str,
        max_results: int,
        total_results: int | None,
        raw_paths: list[str],
        candidates: list[SearchCandidate],
    ) -> SearchSession:
        session = SearchSession(
            session_id=uuid.uuid4().hex,
            query=query,
            created_at=datetime.now(UTC).isoformat(),
            total_results=total_results,
            max_results=max_results,
            candidates=candidates,
            raw_paths=raw_paths,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> SearchSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Search session not found: {session_id}") from exc

    def all(self) -> list[SearchSession]:
        return sorted(self._sessions.values(), key=lambda item: item.created_at, reverse=True)

    def update_selection(self, session_id: str, candidate_ids: list[str]) -> SearchSession:
        session = self.get(session_id)
        wanted: set[str] = set(candidate_ids)
        for candidate in session.candidates:
            candidate.selected = candidate.candidate_id in wanted
        return session

    def selected(self, session_id: str) -> list[SearchCandidate]:
        return [item for item in self.get(session_id).candidates if item.selected]
