"""Application configuration loading and defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    """Local dashboard binding.

    v0.1 exposes no authentication, so the server is intentionally restricted
    to loopback. `allow_non_loopback` exists only as an explicit, documented
    escape hatch for users who knowingly add their own auth/proxy in front.
    """

    host: str = "127.0.0.1"
    port: int = Field(default=8765, gt=0, lt=65536)
    allow_non_loopback: bool = False


class CredentialConfig(BaseModel):
    name: str
    secret_ref: str | None = None
    # Which services this credential may serve. Empty means "any service".
    # Needed when one provider issues separate keys per API (e.g. Springer).
    services: list[str] = Field(default_factory=list)
    api_key_env: str | None = None
    institution: str | None = None
    account_label: str | None = None
    quota_scope: str = "unknown"
    enabled: bool = True

    def secret_ref_for(self, provider: str) -> str:
        """Resolve the secret reference, defaulting to a provider-local file."""
        if self.secret_ref:
            return self.secret_ref
        if self.api_key_env:
            return self.api_key_env if ":" in self.api_key_env else f"env:{self.api_key_env}"
        return f"file:{provider}:{self.name}"

    @property
    def resolved_secret_ref(self) -> str:
        """Backwards-compatible accessor for the default (Elsevier) provider."""
        return self.secret_ref_for("elsevier")


class ServiceConfig(BaseModel):
    enabled: bool = True


class PolicyConfig(BaseModel):
    """Pacing and daily ceilings for one provider.

    Defaults are deliberately gentle: publishers meter access per institution,
    so one aggressive client can affect every researcher at the same university.
    Set `unlimited: true` only when you have explicit written authorization.
    """

    unlimited: bool = False
    fulltext_min_interval_seconds: float = Field(default=60.0, ge=0)
    pdf_min_interval_seconds: float = Field(default=120.0, ge=0)
    search_min_interval_seconds: float = Field(default=5.0, ge=0)
    fulltext_daily_limit: int | None = Field(default=100, ge=0)
    pdf_daily_limit: int | None = Field(default=50, ge=0)
    search_daily_limit: int | None = Field(default=200, ge=0)
    jitter_ratio: float = Field(default=0.25, ge=0, le=1)


class ProviderConfig(BaseModel):
    """Configuration for one external provider.

    Kept generic so adding a publisher is a configuration change rather than a
    code change. Provider-specific defaults live in the provider implementation.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    base_url: str | None = None
    timeout_seconds: float = 30.0
    download_pdf: bool = False
    contact_email: str | None = None
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    services: dict[str, ServiceConfig] = Field(default_factory=dict)
    credentials: list[CredentialConfig] = Field(default_factory=list)

    def service_enabled(self, name: str) -> bool:
        service = self.services.get(name)
        return bool(service.enabled) if service else True


class OpenAlexConfig(ProviderConfig):
    """OpenAlex defaults. No API key is required; an email joins the polite pool."""

    base_url: str = "https://api.openalex.org"
    contact_email: str | None = None
    services: dict[str, ServiceConfig] = Field(
        default_factory=lambda: {
            "works_search": ServiceConfig(),
            "works_lookup": ServiceConfig(),
        }
    )


class SpringerConfig(ProviderConfig):
    """Springer Nature defaults.

    Springer issues separate keys for the Meta and OpenAccess APIs, which is why
    credentials can declare a `services` allowlist.
    """

    base_url: str = "https://api.springernature.com"
    services: dict[str, ServiceConfig] = Field(
        default_factory=lambda: {
            "springer_meta": ServiceConfig(),
            "springer_openaccess": ServiceConfig(),
        }
    )


class ElsevierConfig(ProviderConfig):
    """Elsevier defaults, kept for backwards compatibility."""

    base_url: str = "https://api.elsevier.com"
    services: dict[str, ServiceConfig] = Field(
        default_factory=lambda: {
            "scopus_search": ServiceConfig(),
            "article_retrieval": ServiceConfig(),
            "article_pdf": ServiceConfig(),
        }
    )


def _default_providers() -> dict[str, ProviderConfig]:
    # OpenAlex needs no credentials, so it is enabled out of the box.
    return {"elsevier": ElsevierConfig(), "openalex": OpenAlexConfig()}


class ProvidersConfig(BaseModel):
    """Registry of configured providers, keyed by provider name.

    Accepts both the modern shape::

        providers:
          entries:
            elsevier: {...}

    and the original (still supported) shape::

        providers:
          elsevier: {...}
    """

    entries: dict[str, ProviderConfig] = Field(default_factory=_default_providers)

    @model_validator(mode="before")
    @classmethod
    def _normalize_shape(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        legacy = {key: item for key, item in value.items() if key != "entries"}
        declared = value.get("entries")
        entries: dict[str, object] = dict(declared) if isinstance(declared, dict) else {}
        # `providers: {}` means "use defaults", not "no providers at all".
        if not entries and not legacy:
            return {"entries": {name: item for name, item in _default_providers().items()}}
        for name, item in legacy.items():
            existing = entries.get(name)
            if isinstance(existing, dict) and isinstance(item, dict):
                merged = dict(existing)
                merged.update(item)
                entries[name] = merged
            else:
                entries[name] = item
        return {"entries": entries}

    # --- accessors -------------------------------------------------------

    def get(self, name: str) -> ProviderConfig:
        try:
            return self.entries[name]
        except KeyError as exc:
            raise KeyError(f"Provider is not configured: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self.entries)

    def all(self) -> dict[str, ProviderConfig]:
        return dict(self.entries)

    def enabled(self) -> dict[str, ProviderConfig]:
        return {name: item for name, item in self.entries.items() if item.enabled}

    @property
    def elsevier(self) -> ProviderConfig:
        """Backwards-compatible accessor."""
        return self.entries.get("elsevier", ElsevierConfig())


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

    # Runtime overrides (for example a storage directory chosen in the web UI)
    # take precedence over config.yaml, but are stored outside version control.
    from lit_harvest.settings import SettingsStore

    overrides: dict[str, Any] = {}
    try:
        stored = SettingsStore(selected).load()
    except OSError:
        stored = None
    if stored is not None:
        if stored.storage_root:
            overrides.setdefault("storage", {})["root"] = stored.storage_root
        if stored.database_url:
            overrides.setdefault("database", {})["url"] = stored.database_url

    defaults = AppConfig().model_dump(mode="python")
    merged = _merge(defaults, raw)
    if overrides:
        merged = _merge(merged, overrides)
    model_config = AppConfig.model_validate(merged)
    model_config.config_path = selected.resolve() if selected else None
    return model_config.resolve_paths()
