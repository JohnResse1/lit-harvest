"""FastAPI application factory for the local dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lit_harvest import __version__
from lit_harvest.api.events import router as events_router
from lit_harvest.api.routes.jobs import router as jobs_router
from lit_harvest.api.routes.papers import router as papers_router
from lit_harvest.api.routes.providers import router as providers_router
from lit_harvest.api.routes.system import router as system_router
from lit_harvest.config import AppConfig, load_config
from lit_harvest.services.container import ServiceContainer

STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: AppConfig | None = None) -> FastAPI:
    application = FastAPI(
        title="Literature Harvester",
        version=__version__,
        description="Local-first literature discovery, acquisition, and normalization.",
    )
    application.state.container = ServiceContainer(config or load_config())
    application.include_router(system_router, prefix="/api")
    application.include_router(papers_router, prefix="/api")
    application.include_router(providers_router, prefix="/api")
    application.include_router(jobs_router, prefix="/api")
    application.include_router(events_router, prefix="/api")

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
            return FileResponse(STATIC_DIR / "index.html")

    return application


app = create_app
