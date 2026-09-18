import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ProvidersConfig,
    StorageConfig,
    load_config,
)
from lit_harvest.demo.generator import generate_demo_data
from lit_harvest.services.container import ServiceContainer
from lit_harvest.services.storage_settings import StorageChangeError
from lit_harvest.settings import RuntimeSettings, SettingsStore


def make_config(root: Path, config_path: Path | None = None) -> AppConfig:
    config = AppConfig(
        storage=StorageConfig(root=root),
        database=DatabaseConfig(url=f"sqlite:///{root / 'lit_harvest.db'}"),
        providers=ProvidersConfig(),
    )
    config.config_path = config_path
    return config


def test_storage_describe_reports_default(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config = make_config(tmp_path / "data", config_path)
    container = ServiceContainer(config)
    paths = container.storage_settings.describe()
    assert paths.is_default is True
    assert paths.writable is True
    assert paths.paper_directories == 0


def test_storage_validate_rejects_file(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    container = ServiceContainer(config)
    a_file = tmp_path / "not-a-dir.txt"
    a_file.write_text("x", encoding="utf-8")
    result = container.storage_settings.validate(str(a_file))
    assert result.ok is False
    assert "file" in result.message.lower()


def test_storage_validate_accepts_new_directory(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    container = ServiceContainer(config)
    target = tmp_path / "external" / "papers-here"
    result = container.storage_settings.validate(str(target))
    assert result.ok is True
    assert result.writable is True
    assert result.empty is True


def test_storage_change_migrates_papers_and_rewrites_paths(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    container = ServiceContainer(config)
    generate_demo_data(container)
    assert container.database.count_papers() == 3

    target = tmp_path / "moved"
    result = container.storage_settings.change(str(target), migrate=True)

    assert result["migrated_papers"] == 3
    assert (target / "lit_harvest.db").exists()
    assert len(list((target / "papers").iterdir())) == 3

    # Recorded file paths must point at files that really exist.
    connection = sqlite3.connect(str(target / "lit_harvest.db"))
    try:
        rows = connection.execute("SELECT raw_path FROM downloads").fetchall()
    finally:
        connection.close()
    assert rows
    for (raw_path,) in rows:
        assert str(target) in raw_path
        assert Path(raw_path).exists()


def test_storage_change_writes_settings_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = project / "config.yaml"
    config = make_config(project / "data", config_path)
    container = ServiceContainer(config)
    target = tmp_path / "elsewhere"

    container.storage_settings.change(str(target), migrate=False)

    settings_file = project / ".lit-harvest" / "settings.json"
    assert settings_file.exists()
    payload = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["storage_root"] == str(target)
    assert str(target) in payload["database_url"]


def test_stored_settings_override_config_on_reload(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config_path = project / "config.yaml"
    config_path.write_text(
        "storage:\n  root: ./data\ndatabase:\n  url: sqlite:///./data/lit_harvest.db\n",
        encoding="utf-8",
    )
    elsewhere = tmp_path / "elsewhere"
    SettingsStore(config_path).save(
        RuntimeSettings(
            storage_root=str(elsewhere),
            database_url=f"sqlite:///{elsewhere / 'lit_harvest.db'}",
        )
    )

    reloaded = load_config(config_path)

    assert reloaded.storage.root == elsewhere.resolve()
    assert str(elsewhere) in reloaded.database.url


def test_storage_change_refuses_non_empty_target(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    container = ServiceContainer(config)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing.txt").write_text("mine", encoding="utf-8")

    import pytest

    with pytest.raises(StorageChangeError, match="not empty"):
        container.storage_settings.change(str(target), migrate=False)


def test_storage_change_allows_overwrite_when_forced(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    container = ServiceContainer(config)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing.txt").write_text("mine", encoding="utf-8")

    result = container.storage_settings.change(str(target), migrate=False, force=True)
    assert result["restart_required"] is True


def test_storage_api_endpoints(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    client = TestClient(create_app(config, start_worker=False))

    current = client.get("/api/settings/storage")
    assert current.status_code == 200
    assert current.json()["is_default"] is True

    target = tmp_path / "api-target"
    validated = client.get(f"/api/settings/storage/validate?path={target}")
    assert validated.status_code == 200
    assert validated.json()["ok"] is True

    changed = client.post(
        "/api/settings/storage",
        json={"path": str(target), "migrate": False, "overwrite": False},
    )
    assert changed.status_code == 200
    assert changed.json()["restart_required"] is True

    reset = client.post("/api/settings/storage/reset")
    assert reset.status_code == 200


def test_storage_api_rejects_bad_path(tmp_path: Path) -> None:
    config = make_config(tmp_path / "data", tmp_path / "config.yaml")
    client = TestClient(create_app(config, start_worker=False))
    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    response = client.get(f"/api/settings/storage/validate?path={a_file}")
    assert response.status_code == 200
    assert response.json()["ok"] is False
