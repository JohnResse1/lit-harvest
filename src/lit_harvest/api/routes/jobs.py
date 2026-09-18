"""Job, failure, and queue-control routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from lit_harvest.api.dependencies import ContainerDep
from lit_harvest.models import JobStatus, TaskType

router = APIRouter(tags=["jobs"])


class PauseRequest(BaseModel):
    reason: str | None = None


@router.get("/jobs")
def jobs(
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: JobStatus | None = None,
    task_type: TaskType | None = None,
) -> list[dict[str, Any]]:
    return [
        job.model_dump(mode="json")
        for job in container.database.list_jobs(
            limit=limit, offset=offset, status=status, task_type=task_type
        )
    ]


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, container: ContainerDep) -> dict[str, Any]:
    try:
        return container.maintenance.retry_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, container: ContainerDep) -> dict[str, Any]:
    try:
        return container.maintenance.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/queue/pause")
def pause(
    request: PauseRequest,
    container: ContainerDep,
) -> dict[str, Any]:
    container.maintenance.pause(request.reason)
    return {"paused": True, "reason": request.reason}


@router.post("/queue/resume")
def resume(container: ContainerDep) -> dict[str, Any]:
    container.maintenance.resume()
    return {"paused": False}


@router.post("/failures/retry-transient")
def retry_transient(container: ContainerDep) -> dict[str, int]:
    return container.maintenance.retry_transient()


@router.get("/failures")
def failures(
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[dict[str, Any]]:
    return container.database.list_failures(limit=limit)
