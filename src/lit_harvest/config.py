"""Application configuration loading and defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class StorageConfig(BaseModel):
    root: Path = Path("./data")

    @field_validator("root", mode="before")
    @classmethod
    def expand_root(cls, value: str | Path) -> Path:
        return Path(value).expanduser()


class DatabaseConfig(BaseModel):
    url: str = "sqlite:///./data/lit_harvest.db"


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=4, ge=1)
    base_delay_seconds: float = Field(default=2.0, gt=0)
    max_delay_seconds: float = Field(default=300.0, gt=0)


class RateLimitConfig(BaseModel):
    respect_retry_after: bool = True


class QuotaConfig(BaseModel):
    warning_ratio: float = Field(default=0.30, ge=0, le=1)
    low_ratio: float = Field(default=0.10, ge=0, le=1)


class SchedulerConfig(BaseModel):
    retry: RetryConfig = Field(default_factory=RetryConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    quota: QuotaConfig = Field(default_factory=QuotaConfig)


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, gt=0, lt=65536)


class CredentialConfig(BaseModel):
    name: str
    secret_ref: str | None = None
    api_key_env: str | None = None
    institution: str | None = None
    account_label: str | None = None
    quota_scope: str = "unknown"
    enabled: bool = True

    @property
    def resolved_secret_ref(self) -> str:
        if self.secret_ref:
            return self.secret_ref
        if self.api_key_env:
            return self.api_key_env if ":" in self.api_key_env else f"env:{self.api_key_env}"
        return f"file:elsevier:{self.name}"


class ServiceConfig(BaseModel):
    enabled: bool = True


class ElsevierConfig(BaseModel):
    enabled: bool = True
    base_url: str = "https://api.elsevier.com"
    timeout_seconds: float = 30.0
    services: dict[str, ServiceConfig] = Field(
        default_factory=lambda: {
            "scopus_search": ServiceConfig(),
            "article_retrieval": ServiceConfig(),
        }
    )
    credentials: list[CredentialConfig] = Field(default_factory=list)


class ProvidersConfig(BaseModel):
    elsevier: ElsevierConfig = Field(default_factory=ElsevierConfig)


class AppConfig(BaseModel):
    storage: StorageConfig = Field(default_factory=StorageConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    config_path: Path | None = None

    @property
    def database_path(self) -> Path | None:
        prefix = "sqlite:///"
        if not self.database.url.startswith(prefix):
            return None
        raw = self.database.url[len(prefix) :]
        if raw == ":memory:":
            return None
        return Path(raw).expanduser()

    def resolve_paths(self, base_dir: Path | None = None) -> AppConfig:
        base = base_dir or (self.config_path.parent if self.config_path else Path.cwd())
        storage_root = self.storage.root
        if not storage_root.is_absolute():
            storage_root = (base / storage_root).resolve()
        self.storage.root = storage_root

        if self.database.url.startswith("sqlite:///") and self.database.url != "sqlite:///:memory:":
            raw = self.database.url[len("sqlite:///") :]
            db_path = Path(raw).expanduser()
            if not db_path.is_absolute():
                db_path = (base / db_path).resolve()
            self.database.url = f"sqlite:///{db_path}"
        return self


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def config_candidates(explicit: str | Path | None = None) -> list[Path]:
    if explicit:
        return [Path(explicit).expanduser()]
    env_path = os.getenv("LIT_HARVEST_CONFIG")
    if env_path:
        return [Path(env_path).expanduser()]
    return [Path.cwd() / "config.yaml", Path.home() / ".config" / "lit-harvest" / "config.yaml"]


def load_config(path: str | Path | None = None) -> AppConfig:
    selected = next(
        (candidate for candidate in config_candidates(path) if candidate.exists()), None
    )
    raw: dict[str, Any] = {}
    if selected:
        with selected.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Configuration root must be a mapping: {selected}")
        raw = loaded

    defaults = AppConfig().model_dump(mode="python")
    model_config = AppConfig.model_validate(_merge(defaults, raw))
    model_config.config_path = selected.resolve() if selected else None
    return model_config.resolve_paths()
