"""API key pool: list, add, update, and health-check provider credentials.

Secrets are write-only over this API. Responses never include a key value, only
whether one is stored and where it comes from.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from lit_harvest.api.dependencies import ContainerDep
from lit_harvest.services.credential_pool import PoolError

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialCreate(BaseModel):
    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    # Accepted on write, never echoed back.
    secret: str | None = None
    secret_ref: str | None = None
    institution: str | None = None
    account_label: str | None = None
    quota_scope: str = "unknown"
    priority: int = 100
    notes: str | None = None
    enabled: bool = True
    # Which services this credential may serve. Empty means "any service".
    # Required when one provider issues a separate key per API, e.g. Springer.
    services: list[str] = Field(default_factory=list)


class CredentialToggle(BaseModel):
    enabled: bool


@router.get("")
def list_credentials(
    container: ContainerDep,
    provider: Annotated[str | None, Query()] = None,
) -> list[dict[str, Any]]:
    return [item.to_dict() for item in container.credential_pool.entries(provider)]


@router.post("")
def add_credential(
    request: CredentialCreate,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        entry = container.credential_pool.add(
            provider=request.provider,
            name=request.name,
            secret=request.secret,
            secret_ref=request.secret_ref,
            institution=request.institution,
            account_label=request.account_label,
            quota_scope=request.quota_scope,
            priority=request.priority,
            notes=request.notes,
            enabled=request.enabled,
            services=request.services or None,
        )
    except PoolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return entry.to_dict()


@router.post("/{credential_id}/enabled")
def toggle_credential(
    credential_id: str,
    request: CredentialToggle,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        return container.credential_pool.set_enabled(credential_id, request.enabled).to_dict()
    except PoolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{credential_id}")
def delete_credential(
    credential_id: str,
    container: ContainerDep,
    delete_secret: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    try:
        return container.credential_pool.remove(credential_id, delete_secret=delete_secret)
    except PoolError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/catalog")
def credential_catalog(container: ContainerDep) -> list[dict[str, Any]]:
    """Providers available in this build, with the services they expose.

    The dashboard uses this to offer only providers that actually work, and to
    pre-select the right service allowlist per provider.
    """
    catalog: list[dict[str, Any]] = []
    for provider in container.providers.all():
        # `resolved_services()` applies provider defaults when the config entry
        # omits `services`, so a minimal `springer: {enabled: true}` still lists
        # its two APIs.
        resolved = container.config.providers.get(provider.name).resolved_services()
        services = sorted(resolved)
        catalog.append(
            {
                "name": provider.name,
                "display_name": provider.display_name,
                "services": services,
                "capabilities": {
                    capability: bool(getattr(provider, f"supports_{capability}", False))
                    for capability in ("search", "fulltext", "pdf", "metadata", "oa_lookup")
                },
                # A provider that needs no key should not ask for one.
                "requires_credential": bool(getattr(provider, "requires_credential", True)),
            }
        )
    return catalog


@router.get("/{provider}/health")
def credential_health(provider: str, container: ContainerDep) -> dict[str, Any]:
    return container.credential_pool.healthcheck(provider)


@router.get("/{provider}/selection")
def selection_preview(
    provider: str,
    container: ContainerDep,
    service: Annotated[str, Query()] = "article_retrieval",
) -> dict[str, Any]:
    return container.credential_pool.selection_preview(provider, service)
