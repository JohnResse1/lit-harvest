"""Provider, credential, and quota routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from lit_harvest.api.dependencies import ContainerDep

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
def providers(container: ContainerDep) -> list[dict[str, Any]]:
    return container.dashboard.providers()


@router.get("/quotas")
def quotas(container: ContainerDep) -> list[dict[str, Any]]:
    return [quota.model_dump(mode="json") for quota in container.database.list_quotas()]
