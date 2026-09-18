"""Phase A: provider decoupling, capability routing, and the resolver."""

from pathlib import Path

import pytest

from lit_harvest.config import (
    AppConfig,
    CredentialConfig,
    DatabaseConfig,
    ElsevierConfig,
    ProviderConfig,
    ProvidersConfig,
    ServiceConfig,
    StorageConfig,
)
from lit_harvest.providers.base import ProviderUnavailableError
from lit_harvest.providers.registry import ProviderRegistry, build_registry
from lit_harvest.services.container import ServiceContainer
from lit_harvest.services.resolver import Resolver


class FakeProvider:
    def __init__(self, name: str, **caps: bool):
        self.name = name
        self.display_name = name.title()
        self.supports_search = caps.get("search", False)
        self.supports_fulltext = caps.get("fulltext", False)
        self.supports_pdf = caps.get("pdf", False)
        self.supports_metadata = caps.get("metadata", False)
        self.search_service = f"{name}_search"
        self.fulltext_service = f"{name}_fulltext"
        self.pdf_service = f"{name}_pdf"

    def healthcheck(self, service=None, *, network=True):
        return []

    def search(self, query, *, max_results, start_year=None, end_year=None):
        return []

    def fetch_fulltext(self, doi):
        raise NotImplementedError


# ---------------------------------------------------------------- config shape


def test_legacy_elsevier_config_still_loads() -> None:
    """The original config.yaml shape must keep working unchanged."""
    providers = ProvidersConfig.model_validate(
        {
            "elsevier": {
                "enabled": True,
                "services": {
                    "scopus_search": {"enabled": True},
                    "article_retrieval": {"enabled": True},
                },
                "credentials": [
                    {
                        "name": "university_primary",
                        "secret_ref": "file:elsevier:university_primary",
                        "institution": "HIT",
                        "quota_scope": "institution",
                    }
                ],
            }
        }
    )
    assert providers.names() == ["elsevier"]
    assert providers.elsevier.enabled is True
    assert [c.name for c in providers.elsevier.credentials] == ["university_primary"]


def test_modern_config_supports_multiple_providers() -> None:
    providers = ProvidersConfig.model_validate(
        {
            "entries": {
                "elsevier": {"enabled": True},
                "springer": {
                    "enabled": True,
                    "base_url": "https://api.springernature.com",
                    "credentials": [{"name": "primary", "secret_ref": "file:springer:primary"}],
                },
            }
        }
    )
    assert providers.names() == ["elsevier", "springer"]
    assert providers.enabled()["springer"].base_url == "https://api.springernature.com"


def test_missing_provider_raises() -> None:
    providers = ProvidersConfig()
    with pytest.raises(KeyError):
        providers.get("unknown-provider")


def test_secret_ref_defaults_to_its_own_provider() -> None:
    """A credential without an explicit ref must not point at Elsevier."""
    credential = CredentialConfig(name="primary")
    assert credential.secret_ref_for("springer") == "file:springer:primary"
    assert credential.secret_ref_for("elsevier") == "file:elsevier:primary"


def test_provider_service_enabled_lookup() -> None:
    config = ProviderConfig(
        services={"search": ServiceConfig(enabled=False), "fetch": ServiceConfig(enabled=True)}
    )
    assert config.service_enabled("search") is False
    assert config.service_enabled("fetch") is True
    # Unknown services default to enabled.
    assert config.service_enabled("other") is True


# ------------------------------------------------------------- registry / caps


def test_registry_filters_by_capability() -> None:
    search_only = FakeProvider("openalex", search=True, metadata=True)
    fulltext_only = FakeProvider("springer", fulltext=True, pdf=True)
    registry = build_registry([search_only, fulltext_only])

    assert registry.names() == ["openalex", "springer"]
    assert [p.name for p in registry.search_providers()] == ["openalex"]
    assert [p.name for p in registry.fulltext_providers()] == ["springer"]
    assert [p.name for p in registry.pdf_providers()] == ["springer"]
    assert registry.first_with_capability("supports_search") is search_only


def test_registry_first_with_capability_returns_none_when_absent() -> None:
    registry = build_registry([FakeProvider("openalex", search=True)])
    assert registry.first_with_capability("supports_pdf") is None


def test_registry_keeps_backwards_compatible_list_alias() -> None:
    registry = build_registry([FakeProvider("a", search=True)])
    assert len(registry.list()) == 1
    assert registry.list() == registry.all()


# ------------------------------------------------------------------- resolver


def test_resolver_ranks_structured_xml_above_pdf() -> None:
    resolver = Resolver(build_registry([FakeProvider("elsevier", fulltext=True, pdf=True)]))
    candidates = resolver.candidates("10.1000/x", want_pdf=True)
    assert [c.format for c in candidates] == ["xml", "pdf"]
    assert candidates[0].quality > candidates[1].quality


def test_resolver_omits_pdf_when_not_requested() -> None:
    resolver = Resolver(build_registry([FakeProvider("elsevier", fulltext=True, pdf=True)]))
    assert [c.format for c in resolver.candidates("10.1000/x")] == ["xml"]


def test_resolver_prefers_higher_quality_across_providers() -> None:
    xml_provider = FakeProvider("publisher", fulltext=True)
    pdf_only = FakeProvider("repository", pdf=True)
    resolver = Resolver(build_registry([pdf_only, xml_provider]))
    best = resolver.best("10.1000/x", want_pdf=True)
    assert best is not None
    assert best.provider == "publisher"


def test_resolver_returns_none_without_capable_provider() -> None:
    resolver = Resolver(build_registry([FakeProvider("metadata-only", metadata=True)]))
    assert resolver.best("10.1000/x") is None


# ------------------------------------------------------------------ container


def test_container_registers_only_enabled_providers(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={
                "elsevier": ElsevierConfig(enabled=True),
                "springer": ProviderConfig(enabled=False),
            }
        ),
    )
    container = ServiceContainer(config)
    assert container.providers.names() == ["elsevier"]


def test_container_ignores_configured_but_unimplemented_provider(tmp_path: Path) -> None:
    """A shared config must not crash an instance that lacks that provider."""
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={
                "elsevier": ElsevierConfig(enabled=True),
                "future-publisher": ProviderConfig(enabled=True),
            }
        ),
    )
    container = ServiceContainer(config)
    assert "future-publisher" not in container.providers.names()
    assert container.providers.names() == ["elsevier"]


def test_dashboard_quota_runways_follow_configured_providers(tmp_path: Path) -> None:
    from lit_harvest.models import QuotaScope, QuotaSource, QuotaUpdate

    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": ElsevierConfig()}),
    )
    container = ServiceContainer(config)
    container.database.upsert_quota(
        QuotaUpdate(
            provider="elsevier",
            service="scopus_search",
            remaining=10,
            source=QuotaSource.LOCAL_ESTIMATE,
            quota_scope=QuotaScope.INSTITUTION,
        )
    )
    overview = container.dashboard.overview()
    services = {item["service"] for item in overview["quota"]["runways"]}
    # Comes from persisted quota rows, not a hardcoded Elsevier pair.
    assert services == {"scopus_search"}


def test_acquisition_reports_when_no_search_provider(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": ElsevierConfig(enabled=False)}),
    )
    container = ServiceContainer(config)
    container.providers = ProviderRegistry()
    container.acquisition.providers = container.providers
    container.acquisition.resolver = Resolver(container.providers)
    with pytest.raises(ProviderUnavailableError, match="supports literature search"):
        container.acquisition.search("test", max_results=1)
