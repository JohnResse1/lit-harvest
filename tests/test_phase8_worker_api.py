from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import AppConfig, DatabaseConfig, ProvidersConfig, StorageConfig
from lit_harvest.models import JobCreate, JobStatus, TaskType
from lit_harvest.scheduler.worker import Worker


def test_worker_runs_queued_job(tmp_path: Path) -> None:
    from lit_harvest.scheduler.scheduler import Scheduler
    from lit_harvest.storage.database import Database

    database = Database(f"sqlite:///{tmp_path / 'state.db'}")
    database.initialize()
    scheduler = Scheduler(database)
    scheduler.register(TaskType.NORMALIZE, lambda job: {"job_id": job.id})
    database.create_job(JobCreate(task_type=TaskType.NORMALIZE))
    worker = Worker(scheduler, poll_interval_seconds=0.1)
    result = worker.run_once()
    assert result.succeeded == 1
    assert worker.state.ticks == 1
    assert database.count_jobs(JobStatus.SUCCESS) == 1


def test_worker_pause_stops_execution(tmp_path: Path) -> None:
    from lit_harvest.scheduler.scheduler import Scheduler
    from lit_harvest.storage.database import Database

    database = Database(f"sqlite:///{tmp_path / 'state.db'}")
    database.initialize()
    scheduler = Scheduler(database)
    scheduler.register(TaskType.NORMALIZE, lambda job: {})
    database.create_job(JobCreate(task_type=TaskType.NORMALIZE))
    scheduler.pause("test")
    worker = Worker(scheduler, poll_interval_seconds=0.1)
    result = worker.run_once()
    assert result.attempted == 0
    assert database.count_jobs(JobStatus.PENDING) == 1


def api_client(tmp_path: Path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    return TestClient(create_app(config, start_worker=False))


def test_api_worker_status_and_tick(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    status = client.get("/api/worker")
    assert status.status_code == 200
    assert status.json()["alive"] is False
    tick = client.post("/api/worker/tick?max_jobs=1")
    assert tick.status_code == 200
    assert tick.json()["attempted"] == 0


def test_api_search_endpoint_validation(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    invalid = client.post("/api/search", json={"query": "x", "max_results": 0})
    assert invalid.status_code == 422


def test_api_export_download_headers(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    response = client.get("/api/papers/export?format=csv&download=true")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers.get("content-disposition", "")


def test_api_zip_download_empty_is_404(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    response = client.post("/api/papers/download/zip", json={"include_pdf": True})
    assert response.status_code == 404
