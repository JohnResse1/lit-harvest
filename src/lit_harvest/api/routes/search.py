"""Discovery search route."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from lit_harvest.api.dependencies import ContainerDep

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    max_results: int = 100
    start_year: int | None = None
    end_year: int | None = None


@router.post("")
def run_search(request: SearchRequest, container: ContainerDep) -> dict[str, Any]:
    if request.max_results < 1:
        raise HTTPException(status_code=422, detail="max_results must be >= 1")
    try:
        result = container.acquisition.search(
            request.query,
            max_results=request.max_results,
            start_year=request.start_year,
            end_year=request.end_year,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the local caller
        raise HTTPException(
            status_code=502,
            detail={"code": getattr(exc, "code", "search_failed"), "message": str(exc)},
        ) from exc
    session = (
        container.acquisition.search_sessions.get(result.session_id) if result.session_id else None
    )
    return {
        "query": result.query,
        "discovered": result.discovered,
        "stored": result.stored,
        "pages": result.pages,
        "total_results": result.total_results,
        "raw_paths": result.raw_paths,
        "session_id": result.session_id,
        "candidates": [item.to_dict() for item in session.candidates] if session else [],
    }


class SelectionRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    download_pdf: bool = False


@router.get("/sessions")
def list_sessions(container: ContainerDep) -> list[dict[str, Any]]:
    return [session.to_dict() for session in container.acquisition.search_sessions.all()]


@router.get("/sessions/{session_id}")
def get_session(session_id: str, container: ContainerDep) -> dict[str, Any]:
    try:
        return container.acquisition.search_sessions.get(session_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/select")
def select_candidates(
    session_id: str,
    request: SelectionRequest,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        session = container.acquisition.search_sessions.update_selection(
            session_id, request.candidate_ids
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "session_id": session.session_id,
        "selected_count": sum(1 for item in session.candidates if item.selected),
    }


@router.post("/sessions/{session_id}/download")
def download_selected(
    session_id: str,
    request: SelectionRequest,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        if request.candidate_ids:
            container.acquisition.search_sessions.update_selection(
                session_id, request.candidate_ids
            )
        return container.acquisition.fetch_selected(session_id, download_pdf=request.download_pdf)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to the local caller
        raise HTTPException(
            status_code=502,
            detail={"code": getattr(exc, "code", "fetch_failed"), "message": str(exc)},
        ) from exc


@router.get("")
def search_get(
    container: ContainerDep,
    query: Annotated[str, Query(min_length=1)],
    max_results: Annotated[int, Query(ge=1, le=5000)] = 100,
    start_year: int | None = None,
    end_year: int | None = None,
) -> dict[str, Any]:
    return run_search(
        SearchRequest(
            query=query,
            max_results=max_results,
            start_year=start_year,
            end_year=end_year,
        ),
        container,
    )
