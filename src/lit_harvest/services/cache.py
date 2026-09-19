"""Manage the raw full-text cache.

Publisher agreements typically require deleting the original full text when a
project ends, while allowing derived (normalized/extracted) results to be kept.
This service makes that lifecycle explicit:

  cached  -> the original XML/PDF is present on disk
  missing -> only derived data remains; the raw file can be re-fetched by DOI

The DOI and normalized document stay in the database either way, so a corpus can
be rebuilt later without rediscovering the papers.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lit_harvest.models import Paper, PaperStage
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage


@dataclass(slots=True)
class CacheStatus:
    paper_id: str
    doi: str | None
    raw_present: bool
    raw_files: int
    normalized_present: bool
    total_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "paper_id": self.paper_id,
            "doi": self.doi,
            "raw_present": self.raw_present,
            "raw_files": self.raw_files,
            "normalized_present": self.normalized_present,
            "total_bytes": self.total_bytes,
        }


@dataclass(slots=True)
class CleanupResult:
    scanned: int = 0
    cleaned: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_freed: int = 0
    cleaned_dois: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "cleaned": self.cleaned,
            "skipped": self.skipped,
            "failed": self.failed,
            "bytes_freed": self.bytes_freed,
            "megabytes_freed": round(self.bytes_freed / 1_048_576, 2),
            "cleaned_dois": self.cleaned_dois,
        }


@dataclass(slots=True)
class RebuildTarget:
    paper_id: str
    doi: str

    def to_dict(self) -> dict[str, str]:
        return {"paper_id": self.paper_id, "doi": self.doi}


class CacheService:
    """Inspect, clean, and rebuild the local full-text cache."""

    def __init__(self, database: Database, storage: DocumentStorage):
        self.database = database
        self.storage = storage

    # ------------------------------------------------------------- inspection

    def status(self, paper: Paper) -> CacheStatus:
        if not paper.doi:
            return CacheStatus(paper.id, None, False, 0, False, 0)
        raw_dir = self.storage.raw_dir(paper.doi)
        normalized = self.storage.normalized_dir(paper.doi) / "paper.json"
        files = [item for item in raw_dir.iterdir() if item.is_file()] if raw_dir.exists() else []
        return CacheStatus(
            paper_id=paper.id,
            doi=paper.doi,
            raw_present=bool(files),
            raw_files=len(files),
            normalized_present=normalized.exists(),
            total_bytes=sum(item.stat().st_size for item in files),
        )

    def summary(self) -> dict[str, float]:
        scanned = cached = missing = normalized = 0
        bytes_cached = 0
        for paper in self.database.list_papers(limit=100_000):
            status = self.status(paper)
            scanned += 1
            if status.raw_present:
                cached += 1
                bytes_cached += status.total_bytes
            else:
                missing += 1
            if status.normalized_present:
                normalized += 1
        return {
            "papers": scanned,
            "raw_cached": cached,
            "raw_missing": missing,
            "normalized_available": normalized,
            "cached_bytes": bytes_cached,
            "cached_megabytes": round(bytes_cached / 1_048_576, 2),
        }

    def missing_raw(self, *, limit: int = 1000) -> list[RebuildTarget]:
        """Papers that have no raw file on disk but do have a DOI."""
        targets: list[RebuildTarget] = []
        for paper in self.database.list_papers(limit=limit):
            if not paper.doi:
                continue
            if self.status(paper).raw_present:
                continue
            targets.append(RebuildTarget(paper_id=paper.id, doi=paper.doi))
        return targets

    # ---------------------------------------------------------------- cleanup

    def cleanup_raw(
        self,
        *,
        paper_ids: list[str] | None = None,
        keep_normalized: bool = True,
        limit: int = 100_000,
    ) -> CleanupResult:
        """Delete cached raw full text, keeping derived data.

        `keep_normalized` controls whether `normalized/paper.json` survives.
        When it does, the paper stays usable for search and extraction even
        though the original publisher document is gone.
        """
        result = CleanupResult()
        selected = set(paper_ids) if paper_ids else None
        for paper in self.database.list_papers(limit=limit):
            if selected is not None and paper.id not in selected:
                continue
            if not paper.doi:
                result.skipped += 1
                continue
            result.scanned += 1

            raw_dir = self.storage.raw_dir(paper.doi)
            if not raw_dir.exists() or not any(raw_dir.iterdir()):
                result.skipped += 1
                continue

            freed = sum(item.stat().st_size for item in raw_dir.iterdir() if item.is_file())
            try:
                shutil.rmtree(raw_dir)
                if not keep_normalized:
                    normalized_dir = self.storage.normalized_dir(paper.doi)
                    if normalized_dir.exists():
                        shutil.rmtree(normalized_dir)
            except OSError:
                result.failed += 1
                continue

            self._record_cache_state(paper, keep_normalized=keep_normalized)
            result.cleaned += 1
            result.bytes_freed += freed
            result.cleaned_dois.append(paper.doi)

        return result

    def _record_cache_state(self, paper: Paper, *, keep_normalized: bool) -> None:
        extra: dict[str, object] = {
            "raw_deleted_at": datetime.now(UTC).isoformat(),
            "raw_cached": False,
        }
        if not keep_normalized:
            extra["normalized_path"] = None
        self.database.add_paper_extra(paper.id, extra)
        # A paper with only metadata stays selectable for a later rebuild.
        if not keep_normalized:
            self.database.set_paper_stage(paper.id, PaperStage.DISCOVERED)
        elif paper.stage not in {PaperStage.NORMALIZED, PaperStage.READY}:
            self.database.set_paper_stage(paper.id, PaperStage.NORMALIZED)

    # ---------------------------------------------------------------- rebuild

    def record_rebuilt(self, paper: Paper) -> None:
        self.database.add_paper_extra(
            paper.id,
            {
                "raw_cached": True,
                "raw_restored_at": datetime.now(UTC).isoformat(),
            },
        )

    def cache_root(self) -> Path:
        return self.storage.root
