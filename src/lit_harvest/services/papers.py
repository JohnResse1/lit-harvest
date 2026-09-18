"""Paper registry service."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from lit_harvest.models import Paper, PaperCreate, PaperStage
from lit_harvest.storage.database import Database


class PaperService:
    def __init__(self, database: Database):
        self.database = database

    def upsert(self, paper: PaperCreate) -> Paper:
        return self.database.upsert_paper(paper)

    def get(self, paper_id: str) -> Paper | None:
        return self.database.get_paper(paper_id)

    def by_doi(self, doi: str) -> Paper | None:
        return self.database.get_paper_by_doi(doi)

    def list(
        self, *, limit: int = 100, offset: int = 0, stage: PaperStage | None = None
    ) -> list[Paper]:
        return self.database.list_papers(limit=limit, offset=offset, stage=stage)

    def detail(self, paper_id: str) -> dict[str, Any] | None:
        paper = self.database.get_paper(paper_id)
        if paper is None:
            return None
        downloads = self.database.list_downloads(paper_id)
        normalized_path = paper.extra.get("normalized_path")
        counts = paper.extra.get("counts", {})
        return {
            "paper": paper.model_dump(mode="json"),
            "downloads": downloads,
            "acquisition": downloads[-1] if downloads else None,
            "parsing": counts,
            "files": {
                "raw": downloads[-1].get("raw_path") if downloads else None,
                "normalized": normalized_path,
            },
            "normalized": paper.extra.get("normalized"),
        }

    def export(self, path: str | Path, *, format: str | None = None, limit: int = 100_000) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        selected_format = format or target.suffix.lstrip(".").lower() or "csv"
        papers = self.database.list_papers(limit=limit)
        if selected_format == "jsonl":
            with target.open("w", encoding="utf-8") as handle:
                for paper in papers:
                    handle.write(
                        json.dumps(paper.model_dump(mode="json"), ensure_ascii=False) + "\n"
                    )
        elif selected_format == "json":
            payload = [paper.model_dump(mode="json") for paper in papers]
            target.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        elif selected_format == "csv":
            with target.open("w", encoding="utf-8", newline="") as handle:
                self._write_csv(handle, papers)
        else:
            raise ValueError(f"Unsupported export format: {selected_format}")
        return target

    @staticmethod
    def _write_csv(handle: TextIO, papers: Sequence[Paper]) -> None:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "doi",
                "scopus_id",
                "eid",
                "pii",
                "title",
                "journal",
                "publication_year",
                "publisher",
                "document_type",
                "discovery_source",
                "stage",
                "created_at",
                "updated_at",
            ],
        )
        writer.writeheader()
        for paper in papers:
            writer.writerow(
                {
                    "id": paper.id,
                    "doi": paper.doi,
                    "scopus_id": paper.identifiers.scopus_id,
                    "eid": paper.identifiers.eid,
                    "pii": paper.identifiers.pii,
                    "title": paper.title,
                    "journal": paper.journal,
                    "publication_year": paper.publication_year,
                    "publisher": paper.publisher,
                    "document_type": paper.document_type,
                    "discovery_source": paper.discovery_source,
                    "stage": paper.stage,
                    "created_at": paper.created_at.isoformat(),
                    "updated_at": paper.updated_at.isoformat(),
                }
            )
