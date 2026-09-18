"""Discovery search route."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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
    return {
        "query": result.query,
        "discovered": result.discovered,
        "stored": result.stored,
        "pages": result.pages,
        "total_results": result.total_results,
        "raw_paths": result.raw_paths,
    }


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
