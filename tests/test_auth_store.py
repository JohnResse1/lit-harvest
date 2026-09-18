import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lit_harvest.cli import app
from lit_harvest.config import AppConfig, CredentialConfig, ElsevierConfig, ProvidersConfig
from lit_harvest.credentials.store import SecretStore, default_secret_ref, parse_secret_ref
from lit_harvest.services.container import ServiceContainer


def test_secret_reference_parsing() -> None:
    assert parse_secret_ref("keychain:svc:acct") == ("keychain", "svc", "acct")
    assert parse_secret_ref("file:my-key") == ("file", "my-key", "")
    assert parse_secret_ref("env:MY_KEY") == ("env", "MY_KEY", "")
    with pytest.raises(ValueError):
        parse_secret_ref("bad")


def test_file_backend_is_private(tmp_path: Path) -> None:
    store = SecretStore(home=tmp_path / "secrets")
    location = store.set("file:primary", "secret-value")
    assert location.backend == "project-file"
    assert store.get("file:primary") == "secret-value"
    mode = stat.S_IMODE((tmp_path / "secrets" / "secrets.json").stat().st_mode)
    assert mode == 0o600
    assert store.delete("file:primary") is True
    assert store.get("file:primary") is None


def test_env_reference_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_ELSEVIER_KEY", "env-secret")
    store = SecretStore()
    assert store.get("env:MY_ELSEVIER_KEY") == "env-secret"
    with pytest.raises(ValueError):
        store.set("env:MY_ELSEVIER_KEY", "cannot-write")


def test_default_ref_is_project_file() -> None:
    assert default_secret_ref("elsevier", "primary") == "file:elsevier:primary"


def test_credential_reference_defaults_and_legacy_conversion() -> None:
    default = CredentialConfig(name="primary")
    assert default.resolved_secret_ref == "file:elsevier:primary"
    legacy = CredentialConfig(name="legacy", api_key_env="ELSEVIER_LEGACY_KEY")
    assert legacy.resolved_secret_ref == "env:ELSEVIER_LEGACY_KEY"


def test_container_uses_secret_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIT_HARVEST_SECRET_BACKEND", "file")
    store = SecretStore(home=tmp_path / "secrets")
    store.set("file:elsevier:primary", "stored-key")
    config = AppConfig(
        providers=ProvidersConfig(
            elsevier=ElsevierConfig(
                credentials=[
                    CredentialConfig(
                        name="primary",
                        secret_ref="file:elsevier:primary",
                    )
                ]
            )
        )
    )
    container = ServiceContainer(config)
    container.credentials.secrets = store
    credentials = container.credentials.list_credentials("elsevier")
    assert credentials[0].secret_available is True
    assert container.credentials.resolve_secret(credentials[0].id) == "stored-key"


def test_auth_cli_writes_inside_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIT_HARVEST_HOME", raising=False)
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
storage:
  root: {tmp_path / "data"}
database:
  url: sqlite:///{tmp_path / "state.db"}
providers:
  elsevier:
    credentials:
      - name: primary
        secret_ref: file:elsevier:primary
""",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["auth", "set", "elsevier", "primary", "--config", str(config)],
        input="cli-secret\n",
    )
    assert result.exit_code == 0
    assert "Stored" in result.stdout
    secret_file = tmp_path / ".lit-harvest" / "secrets.json"
    payload = json.loads(secret_file.read_text(encoding="utf-8"))
    assert payload["file:elsevier:primary"] == "cli-secret"
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
    listing = runner.invoke(app, ["auth", "list", "--config", str(config)])
    assert listing.exit_code == 0
    assert "primary" in listing.stdout
    assert "yes" in listing.stdout


def test_secret_is_not_persisted_to_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIT_HARVEST_SECRET_BACKEND", "file")
    store = SecretStore(home=tmp_path / "secrets")
    store.set("file:primary", "top-secret")
    config = AppConfig(
        storage={"root": tmp_path / "data"},
        database={"url": f"sqlite:///{tmp_path / 'state.db'}"},
        providers={
            "elsevier": {
                "credentials": [
                    {"name": "primary", "secret_ref": "file:primary"},
                ]
            }
        },
    )
    container = ServiceContainer(config)
    container.credentials.secrets = store
    assert "top-secret" not in (tmp_path / "state.db").read_bytes().decode("latin-1")
