"""Paper and import/export routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from lit_harvest.api.dependencies import ContainerDep
from lit_harvest.models import PaperStage

router = APIRouter(prefix="/papers", tags=["papers"])


class DOIRequest(BaseModel):
    doi: str


@router.get("")
def list_papers(
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    stage: PaperStage | None = None,
) -> list[dict[str, Any]]:
    return [
        paper.model_dump(mode="json")
        for paper in container.papers.list(limit=limit, offset=offset, stage=stage)
    ]


@router.post("/import")
async def import_dois(
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    doi_column: Annotated[str, Query()] = "doi",
) -> dict[str, Any]:
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in {".csv", ".tsv", ".txt", ".json", ".jsonl"}:
        raise HTTPException(status_code=415, detail="Unsupported DOI file type")
    content = await file.read()
    temporary = container.storage.root / "incoming" / f"upload_{id(file)}{suffix}"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(content)
    try:
        result = container.acquisition.import_dois(temporary, doi_column=doi_column)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "queued": result.queued,
        "duplicates": result.duplicates,
        "invalid": result.invalid,
    }


@router.get("/export")
def export_papers(
    container: ContainerDep,
    format: Annotated[str, Query(pattern="^(csv|json|jsonl)$")] = "csv",
) -> dict[str, str]:
    target = container.storage.root / "exports" / f"papers.{format}"
    return {"path": str(container.papers.export(target, format=format))}


@router.post("/doi")
def queue_doi(
    request: DOIRequest,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        paper_id, created = container.acquisition.queue_doi(request.doi)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"paper_id": paper_id, "created": created}


@router.get("/{paper_id}")
def paper_detail(
    paper_id: str,
    container: ContainerDep,
) -> dict[str, Any]:
    detail = container.papers.detail(paper_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return detail
