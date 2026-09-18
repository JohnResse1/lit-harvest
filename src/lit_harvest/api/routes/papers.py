"""Paper, import/export, retrieval, and download routes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from lit_harvest.api.dependencies import ContainerDep
from lit_harvest.models import JobCreate, JobStatus, PaperStage, TaskType

router = APIRouter(prefix="/papers", tags=["papers"])


class DOIRequest(BaseModel):
    doi: str
    download_pdf: bool = False


class BatchDownloadRequest(BaseModel):
    paper_ids: list[str] | None = None
    include_pdf: bool = True
    include_normalized: bool = True


def _detail_or_404(container: ContainerDep, paper_id: str) -> dict[str, Any]:
    detail = container.papers.detail(paper_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return detail


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
    run_now: Annotated[bool, Query()] = False,
    download_pdf: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in {".csv", ".tsv", ".txt", ".json", ".jsonl"}:
        raise HTTPException(status_code=415, detail="Unsupported DOI file type")
    content = await file.read()
    incoming = container.storage.root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    temporary = incoming / f"upload_{id(file)}{suffix}"
    temporary.write_bytes(content)
    try:
        result = container.acquisition.import_dois(temporary, doi_column=doi_column)
    finally:
        temporary.unlink(missing_ok=True)
    payload: dict[str, Any] = {
        "queued": result.queued,
        "duplicates": result.duplicates,
        "invalid": result.invalid,
    }
    if run_now:
        run = container.scheduler.run(max_jobs=max(result.queued, 1))
        payload["run"] = {
            "attempted": run.attempted,
            "succeeded": run.succeeded,
            "failed": run.failed,
        }
        if download_pdf:
            pdfs: list[dict[str, Any]] = []
            for paper in container.papers.list(limit=max(result.queued, 1)):
                if not paper.doi:
                    continue
                try:
                    pdfs.append(container.acquisition.fetch_pdf(paper.id))
                except Exception as exc:  # noqa: BLE001 - partial failures are reported
                    pdfs.append(
                        {
                            "paper_id": paper.id,
                            "doi": paper.doi,
                            "error": getattr(exc, "code", "pdf_failed"),
                            "message": str(exc),
                        }
                    )
            payload["pdfs"] = pdfs
    return payload


@router.post("/doi")
def queue_doi(
    request: DOIRequest,
    container: ContainerDep,
    run_now: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    try:
        paper_id, created = container.acquisition.queue_doi(request.doi)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload: dict[str, Any] = {"paper_id": paper_id, "created": created}
    if run_now:
        try:
            job = container.database.create_job(
                JobCreate(
                    task_type=TaskType.FETCH_FULLTEXT,
                    paper_id=paper_id,
                    provider="elsevier",
                    service="article_retrieval",
                    payload={"doi": request.doi},
                )
            )
            fetched = container.acquisition.fetch_job(job)
            container.database.update_job_status(job.id, JobStatus.SUCCESS)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller
            raise HTTPException(
                status_code=502,
                detail={"code": getattr(exc, "code", "fetch_failed"), "message": str(exc)},
            ) from exc
        payload["fetch"] = {
            "raw_path": fetched.raw_path,
            "normalized_path": fetched.normalized_path,
            "reused": fetched.reused,
        }
    if request.download_pdf:
        try:
            payload["pdf"] = container.acquisition.fetch_pdf(paper_id)
        except Exception as exc:  # noqa: BLE001 - XML success remains valid
            payload["pdf_error"] = {
                "code": getattr(exc, "code", "pdf_failed"),
                "message": str(exc),
            }
    return payload


@router.get("/export")
def export_papers(
    container: ContainerDep,
    format: Annotated[str, Query(pattern="^(csv|json|jsonl)$")] = "csv",
    download: Annotated[bool, Query()] = False,
) -> Any:
    target = container.storage.root / "exports" / f"papers.{format}"
    container.papers.export(target, format=format)
    if download:
        media_types = {
            "csv": "text/csv",
            "json": "application/json",
            "jsonl": "application/x-ndjson",
        }
        return FileResponse(
            target,
            media_type=media_types.get(format, "application/octet-stream"),
            filename=target.name,
        )
    return {"path": str(target)}


@router.post("/download/zip")
def download_batch_zip(request: BatchDownloadRequest, container: ContainerDep) -> StreamingResponse:
    if request.paper_ids is None:
        papers = container.papers.list(limit=10_000)
    else:
        papers = [paper for pid in request.paper_ids if (paper := container.papers.get(pid))]
    if not papers:
        raise HTTPException(status_code=404, detail="No papers matched")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for paper in papers:
            if not paper.doi:
                continue
            base = container.storage.paper_dir(paper.doi)
            prefix = paper.doi.replace("/", "_")
            if request.include_normalized:
                normalized = base / "normalized" / "paper.json"
                if normalized.exists():
                    archive.write(normalized, f"{prefix}/normalized/paper.json")
            raw_dir = base / "raw"
            if raw_dir.exists():
                for raw in sorted(raw_dir.iterdir()):
                    if raw.is_file() and (raw.suffix != ".pdf" or request.include_pdf):
                        archive.write(raw, f"{prefix}/raw/{raw.name}")
            state = base / "state.json"
            if state.exists():
                archive.write(state, f"{prefix}/state.json")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="lit-harvest-papers.zip"'},
    )


@router.get("/{paper_id}/download/{kind}")
def download_paper_file(
    paper_id: str,
    kind: str,
    container: ContainerDep,
) -> FileResponse:
    detail = _detail_or_404(container, paper_id)
    paper = detail["paper"]
    doi = paper.get("doi")
    if not doi:
        raise HTTPException(status_code=409, detail="Paper has no DOI")
    base = container.storage.paper_dir(doi)
    if kind == "xml":
        candidates = sorted((base / "raw").glob("*.xml"))
    elif kind == "pdf":
        candidates = sorted((base / "raw").glob("*.pdf"))
    elif kind == "normalized":
        candidates = [base / "normalized" / "paper.json"]
    else:
        raise HTTPException(status_code=400, detail="kind must be xml, pdf, or normalized")
    if not candidates or not candidates[0].exists():
        raise HTTPException(status_code=404, detail=f"No {kind} file available")
    path = candidates[0]
    media_types = {
        "xml": "application/xml",
        "pdf": "application/pdf",
        "normalized": "application/json",
    }
    return FileResponse(
        path,
        media_type=media_types[kind],
        filename=f"{doi.replace('/', '_')}_{path.name}",
    )


@router.get("/{paper_id}")
def paper_detail(
    paper_id: str,
    container: ContainerDep,
) -> dict[str, Any]:
    return _detail_or_404(container, paper_id)
