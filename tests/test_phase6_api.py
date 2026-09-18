from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ProvidersConfig,
    SchedulerConfig,
    StorageConfig,
)


def test_api_read_and_control_routes(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        scheduler=SchedulerConfig(),
        providers=ProvidersConfig(),
    )
    application = create_app(config)
    client = TestClient(application)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert overview.json()["papers"]["total"] == 0

    imported = client.post(
        "/api/papers/import",
        files={"file": ("papers.csv", "doi\n10.1000/api-test\nbad\n", "text/csv")},
    )
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["queued"] == 1
    assert len(payload["invalid"]) == 1

    papers = client.get("/api/papers").json()
    assert len(papers) == 1
    paper_id = papers[0]["id"]
    detail = client.get(f"/api/papers/{paper_id}")
    assert detail.status_code == 200
    assert detail.json()["paper"]["doi"] == "10.1000/api-test"

    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    job_id = jobs[0]["id"]

    paused = client.post("/api/queue/pause", json={"reason": "test"})
    assert paused.status_code == 200
    assert client.get("/api/overview").json()["queue"]["paused"] is True
    assert client.post("/api/queue/resume").json()["paused"] is False

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"

    providers = client.get("/api/providers")
    assert providers.status_code == 200
    assert providers.json()[0]["name"] == "elsevier"
    assert "secret_ref" not in providers.text

    failures = client.get("/api/failures")
    assert failures.status_code == 200
    assert client.post("/api/failures/retry-transient").json()["retried"] >= 0

    exported = client.get("/api/papers/export?format=jsonl")
    assert exported.status_code == 200
    assert Path(exported.json()["path"]).exists()


def test_api_validation_errors(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
    )
    client = TestClient(create_app(config))
    assert client.get("/api/papers/not-found").status_code == 404
    assert client.post("/api/papers/doi", json={"doi": "bad"}).status_code == 422
