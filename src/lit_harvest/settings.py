"""User-editable runtime settings stored outside version control.

Settings live in ``<project>/.lit-harvest/settings.json`` so that changing the
storage directory survives restarts without rewriting ``config.yaml`` (which may
contain comments a user wants to keep).
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from lit_harvest.storage.files import atomic_write_json


@dataclass(slots=True)
class RuntimeSettings:
    """Optional overrides applied on top of config.yaml."""

    storage_root: str | None = None
    database_url: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> RuntimeSettings:
        storage_root = payload.get("storage_root")
        database_url = payload.get("database_url")
        return cls(
            storage_root=str(storage_root) if isinstance(storage_root, str) else None,
            database_url=str(database_url) if isinstance(database_url, str) else None,
        )


def project_root(config_path: Path | None, *, cwd: Path | None = None) -> Path:
    """Where `.lit-harvest/` lives for this instance."""
    base = config_path.parent if config_path else (cwd or Path.cwd())
    return base.expanduser().resolve()


def settings_path(config_path: Path | None, *, cwd: Path | None = None) -> Path:
    return project_root(config_path, cwd=cwd) / ".lit-harvest" / "settings.json"


class SettingsStore:
    """Read/write the local, Git-ignored settings file."""

    def __init__(self, config_path: Path | None = None, *, cwd: Path | None = None):
        self.root = project_root(config_path, cwd=cwd)
        self.path = settings_path(config_path, cwd=cwd)

    def load(self) -> RuntimeSettings:
        if not self.path.exists():
            return RuntimeSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RuntimeSettings()
        if not isinstance(payload, dict):
            return RuntimeSettings()
        return RuntimeSettings.from_dict(payload)

    def save(self, settings: RuntimeSettings) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, settings.to_dict())
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
        return self.path

    def update(self, **changes: str | None) -> RuntimeSettings:
        settings = self.load()
        for key, value in changes.items():
            if not hasattr(settings, key):
                raise KeyError(f"Unknown setting: {key}")
            setattr(settings, key, value)
        self.save(settings)
        return settings
