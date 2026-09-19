"""System diagnostics and overview routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from lit_harvest.api.dependencies import ContainerDep
from lit_harvest.utils.instance import local_identity

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/instance")
def instance(container: ContainerDep) -> dict[str, str]:
    return local_identity(container.config.storage.root.parent)


@router.get("/overview")
def overview(container: ContainerDep) -> dict[str, Any]:
    return container.dashboard.overview()


@router.get("/cache")
def cache_status(container: ContainerDep) -> dict[str, Any]:
    """How much raw full text is stored locally, and what is missing."""
    summary = container.cache.summary()
    missing = container.cache.missing_raw(limit=50)
    return {**summary, "missing_sample": [item.to_dict() for item in missing]}


@router.post("/cache/cleanup")
def cache_cleanup(
    container: ContainerDep,
    keep_normalized: bool = True,
) -> dict[str, Any]:
    """Delete cached raw full text, keeping derived data."""
    result = container.cache.cleanup_raw(keep_normalized=keep_normalized)
    return result.to_dict()


@router.get("/policy")
def policy_status(container: ContainerDep) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for provider in container.config.providers.names():
        policy = container.policy.policy_for(provider)
        payload = container.policy.describe(provider)
        payload["usage"] = {
            "article_retrieval": container.policy.usage_today(provider, "article_retrieval"),
            "article_pdf": container.policy.usage_today(provider, "article_pdf"),
            "scopus_search": container.policy.usage_today(provider, "scopus_search"),
        }
        payload["fulltext_daily_limit"] = policy.fulltext_daily_limit
        entries.append(payload)
    return entries


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
