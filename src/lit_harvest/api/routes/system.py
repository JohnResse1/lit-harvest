"""System diagnostics and overview routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from lit_harvest.api.dependencies import ContainerDep

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/overview")
def overview(container: ContainerDep) -> dict[str, Any]:
    return container.dashboard.overview()


@router.get("/doctor")
def doctor(
    container: ContainerDep,
    network: bool = False,
) -> dict[str, Any]:
    return dict(container.doctor(network=network))
