"""Runtime settings routes (storage directory, and similar)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from lit_harvest.api.dependencies import ContainerDep
from lit_harvest.services.storage_settings import StorageChangeError

router = APIRouter(prefix="/settings", tags=["settings"])


class StorageChangeRequest(BaseModel):
    path: str = Field(min_length=1)
    migrate: bool = True
    overwrite: bool = False


@router.get("/storage")
def get_storage(container: ContainerDep) -> dict[str, Any]:
    return container.storage_settings.describe().to_dict()


@router.get("/storage/validate")
def validate_storage(
    container: ContainerDep,
    path: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    try:
        return container.storage_settings.validate(path).to_dict()
    except StorageChangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/storage")
def change_storage(
    request: StorageChangeRequest,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        return container.storage_settings.change(
            request.path, migrate=request.migrate, force=request.overwrite
        )
    except StorageChangeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/storage/reset")
def reset_storage(
    container: ContainerDep,
    migrate: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    return container.storage_settings.reset_to_default(migrate=migrate)
