"""Dependency wiring for the API layer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from lit_harvest.services.container import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, ServiceContainer):
        raise RuntimeError("Service container is not initialized")
    return container


def iter_container(request: Request) -> Iterator[ServiceContainer]:
    yield get_container(request)


ContainerDep = Annotated[ServiceContainer, Depends(get_container)]
