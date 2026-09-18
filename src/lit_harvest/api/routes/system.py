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


@router.get("/worker")
def worker_status(container: ContainerDep) -> dict[str, Any]:
    return {
        "alive": container.worker.alive,
        "running": container.worker.state.running,
        "ticks": container.worker.state.ticks,
        "paused": container.scheduler.queue.paused,
        "last_result": container.worker.state.last_result,
    }


@router.post("/worker/tick")
def worker_tick(
    container: ContainerDep,
    max_jobs: int = 25,
) -> dict[str, Any]:
    result = container.worker.run_once(max_jobs=max_jobs)
    return {
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "retried": result.retried,
        "waiting_for_quota": result.waiting_for_quota,
        "failed": result.failed,
        "blocked": result.blocked,
        "stopped_reason": result.stopped_reason,
    }


@router.get("/doctor")
def doctor(
    container: ContainerDep,
    network: bool = False,
) -> dict[str, Any]:
    return dict(container.doctor(network=network))
