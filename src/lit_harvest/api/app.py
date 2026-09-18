"""FastAPI application factory for the local dashboard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lit_harvest import __version__
from lit_harvest.api.events import router as events_router
from lit_harvest.api.routes.jobs import router as jobs_router
from lit_harvest.api.routes.papers import router as papers_router
from lit_harvest.api.routes.providers import router as providers_router
from lit_harvest.api.routes.search import router as search_router
from lit_harvest.api.routes.settings import router as settings_router
from lit_harvest.api.routes.system import router as system_router
from lit_harvest.config import AppConfig, load_config
from lit_harvest.services.container import ServiceContainer

STATIC_DIR = Path(__file__).parent / "static"
# Ship the sample DOI files alongside the package so the dashboard can serve them.
EXAMPLES_DIR = Path(__file__).parent / "examples"


def create_app(config: AppConfig | None = None, *, start_worker: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        container = application.state.container
        if start_worker and not container.worker.alive:
            container.worker.start()
        try:
            yield
        finally:
            container.worker.stop()

    application = FastAPI(
        title="Literature Harvester",
        version=__version__,
        description="Local-first literature discovery, acquisition, and normalization.",
        lifespan=lifespan,
    )
    application.state.container = ServiceContainer(config or load_config())
    application.include_router(system_router, prefix="/api")
    application.include_router(papers_router, prefix="/api")
    application.include_router(providers_router, prefix="/api")
    application.include_router(search_router, prefix="/api")
    application.include_router(settings_router, prefix="/api")
    application.include_router(jobs_router, prefix="/api")
    application.include_router(events_router, prefix="/api")

    if EXAMPLES_DIR.exists():
        application.mount("/examples", StaticFiles(directory=EXAMPLES_DIR), name="examples")

    if STATIC_DIR.exists():
        assets = STATIC_DIR / "assets"
        if assets.exists():
            application.mount("/assets", StaticFiles(directory=assets), name="assets")

        @application.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

        @application.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = STATIC_DIR / path
            if candidate.is_file():
                return FileResponse(candidate)
            # Serving index.html for asset/API/example paths hides 404s behind a
            # successful HTML response. Only fall back for real app routes.
            suffix = Path(path).suffix.lower()
            if suffix and suffix not in {".html"}:
                raise HTTPException(status_code=404, detail=f"Not found: {path}")
            return FileResponse(STATIC_DIR / "index.html")

    return application


app = create_app
