from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ProvidersConfig,
    ServerConfig,
    StorageConfig,
)
from lit_harvest.utils.instance import instance_id, is_loopback, local_identity


def test_loopback_detection_rejects_public_binds() -> None:
    assert is_loopback("127.0.0.1") is True
    assert is_loopback("localhost") is True
    assert is_loopback("127.0.0.5") is True
    assert is_loopback("::1") is True
    # Binding every interface must never be treated as safe.
    assert is_loopback("0.0.0.0") is False
    assert is_loopback("::") is False
    assert is_loopback("192.168.1.10") is False
    assert is_loopback("example.com") is False


def test_instance_id_is_stable_and_git_ignored(tmp_path: Path) -> None:
    first = instance_id(tmp_path)
    second = instance_id(tmp_path)
    assert first == second
    assert len(first) == 32
    assert (tmp_path / ".lit-harvest" / "instance_id").exists()


def test_instance_identity_contains_no_secrets(tmp_path: Path) -> None:
    identity = local_identity(tmp_path)
    assert set(identity) == {"instance_id", "user", "hostname", "project"}
    assert "secret" not in " ".join(identity.values()).lower()


def test_api_instance_endpoint(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
        server=ServerConfig(),
    )
    client = TestClient(create_app(config, start_worker=False))
    payload = client.get("/api/instance").json()
    assert payload["instance_id"]
    assert payload["project"]
    assert "key" not in payload


def test_default_server_binds_loopback_only() -> None:
    config = ServerConfig()
    assert config.host == "127.0.0.1"
    assert config.allow_non_loopback is False
