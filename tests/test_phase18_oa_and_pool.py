"""Open-access first routing and the multi-provider credential pool."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    OpenAlexConfig,
    ProviderConfig,
    ProvidersConfig,
    StorageConfig,
)
from lit_harvest.credentials.store import SecretStore
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.oa import OpenAccessFetcher
from lit_harvest.providers.openalex.provider import OpenAlexProvider
from lit_harvest.providers.registry import ProviderRegistry
from lit_harvest.services.container import ServiceContainer
from lit_harvest.services.credential_pool import CredentialPoolService, PoolError
from lit_harvest.services.resolver import Resolver
from lit_harvest.storage.database import Database

OA_WORK = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1000/oa",
    "title": "Open access paper",
    "open_access": {"is_oa": True, "oa_status": "gold", "oa_url": "https://example.org/landing"},
    "best_oa_location": {
        "pdf_url": "https://example.org/paper.pdf",
        "license": "cc-by",
        "version": "publishedVersion",
    },
    "authorships": [],
    "biblio": {},
}

CLOSED_WORK = {
    "id": "https://openalex.org/W2",
    "doi": "https://doi.org/10.1000/closed",
    "title": "Paywalled paper",
    "open_access": {"is_oa": False},
    "authorships": [],
    "biblio": {},
}


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


# --------------------------------------------------------- open-access lookup


def openalex_with(handler, database: Database) -> OpenAlexProvider:
    client = JsonHttpClient(
        base_url="https://api.openalex.org",
        provider="openalex",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    return OpenAlexProvider(database=database, client=client)


def test_oa_lookup_finds_downloadable_pdf(database: Database) -> None:
    provider = openalex_with(lambda request: httpx.Response(200, json=OA_WORK), database)
    result = provider.fetch_oa_location("10.1000/oa")
    assert result is not None
    assert result["is_oa"] is True
    assert result["downloadable"] is True
    assert result["pdf_url"] == "https://example.org/paper.pdf"
    assert result["license"] == "cc-by"


def test_oa_lookup_reports_missing_oa(database: Database) -> None:
    provider = openalex_with(lambda request: httpx.Response(200, json=CLOSED_WORK), database)
    assert provider.fetch_oa_location("10.1000/closed") is None


def test_oa_location_without_pdf_is_not_downloadable(database: Database) -> None:
    """A landing page alone is evidence of OA, not a downloadable file."""
    work = dict(OA_WORK, best_oa_location={})
    provider = openalex_with(lambda request: httpx.Response(200, json=work), database)
    result = provider.fetch_oa_location("10.1000/oa")
    assert result is not None
    assert result["is_oa"] is True
    assert result["downloadable"] is False


# ------------------------------------------------------------- resolver order


def test_resolver_prefers_free_access_over_publisher(database: Database) -> None:
    openalex = openalex_with(lambda request: httpx.Response(200, json=OA_WORK), database)

    class Publisher:
        name = "elsevier"
        display_name = "Elsevier"
        supports_search = True
        supports_fulltext = True
        supports_pdf = True
        supports_metadata = True
        fulltext_service = "article_retrieval"

    registry = ProviderRegistry([openalex, Publisher()])
    resolver = Resolver(registry)
    candidates = resolver.candidates("10.1000/oa")

    assert candidates, "expected at least one source"
    assert candidates[0].free_access is True
    assert candidates[0].service == "oa_download"
    # Free access must outrank the publisher route.
    assert candidates[0].quality > candidates[-1].quality


def test_resolver_falls_back_to_publisher_when_not_oa(database: Database) -> None:
    openalex = openalex_with(lambda request: httpx.Response(200, json=CLOSED_WORK), database)

    class Publisher:
        name = "elsevier"
        display_name = "Elsevier"
        supports_fulltext = True
        fulltext_service = "article_retrieval"

    resolver = Resolver(ProviderRegistry([openalex, Publisher()]))
    candidates = resolver.candidates("10.1000/closed")
    assert candidates[0].free_access is False
    assert candidates[0].provider == "elsevier"


def test_resolver_caches_oa_lookups(database: Database) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=OA_WORK)

    openalex = openalex_with(handler, database)
    resolver = Resolver(ProviderRegistry([openalex]))
    resolver.oa_lookup("10.1000/oa")
    resolver.oa_lookup("10.1000/oa")
    assert calls["n"] == 1


def test_queue_route_never_touches_the_network(database: Database) -> None:
    """Enqueueing 500 DOIs must not trigger 500 metadata lookups."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("routing at queue time must not perform network calls")

    openalex = openalex_with(handler, database)

    class Publisher:
        name = "elsevier"
        display_name = "Elsevier"
        supports_fulltext = True
        fulltext_service = "article_retrieval"

    resolver = Resolver(ProviderRegistry([openalex, Publisher()]))
    route = resolver.route_for_job("10.1000/whatever")
    assert route is not None
    assert route.provider == "elsevier"


# ----------------------------------------------------------- OA file fetching


def test_oa_fetcher_returns_pdf_bytes() -> None:
    fetcher = OpenAccessFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"%PDF-1.7\nbody", headers={"Content-Type": "application/pdf"}
            )
        )
    )
    payload = fetcher.fetch("https://example.org/paper.pdf")
    assert payload["format"] == "pdf"
    assert payload["content"].startswith(b"%PDF")


def test_oa_fetcher_detects_xml_from_content() -> None:
    fetcher = OpenAccessFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"<?xml version='1.0'?><root/>",
                headers={"Content-Type": "application/xml"},
            )
        )
    )
    assert fetcher.fetch("https://example.org/a.xml")["format"] == "xml"


def test_oa_fetcher_rejects_non_http_url() -> None:
    from lit_harvest.providers.base import PermanentProviderError

    fetcher = OpenAccessFetcher()
    with pytest.raises(PermanentProviderError, match="non-HTTP"):
        fetcher.fetch("file:///etc/passwd")


def test_oa_fetcher_reports_missing_file() -> None:
    from lit_harvest.providers.base import PermanentProviderError

    fetcher = OpenAccessFetcher(
        transport=httpx.MockTransport(lambda request: httpx.Response(404, content=b""))
    )
    with pytest.raises(PermanentProviderError, match="no longer exists"):
        fetcher.fetch("https://example.org/gone.pdf")


def test_oa_fetcher_rejects_html_error_page() -> None:
    from lit_harvest.providers.base import PermanentProviderError

    fetcher = OpenAccessFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"<html>not a paper</html>", headers={"Content-Type": "text/html"}
            )
        )
    )
    payload = fetcher.fetch("https://example.org/page")
    assert payload["format"] == "html"

    fetcher_binary = OpenAccessFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=b"\x00\x01binary", headers={"Content-Type": "application/octet-stream"}
            )
        )
    )
    with pytest.raises(PermanentProviderError, match="did not return a supported document"):
        fetcher_binary.fetch("https://example.org/blob")


def test_open_access_download_avoids_publisher(tmp_path: Path, monkeypatch) -> None:
    """When OA is available, the publisher provider must not be called."""
    calls = {"publisher": 0, "oa": 0}

    def oa_transport(request: httpx.Request) -> httpx.Response:
        calls["oa"] += 1
        return httpx.Response(
            200, content=b"%PDF-1.7\noa", headers={"Content-Type": "application/pdf"}
        )

    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={"openalex": OpenAlexConfig(), "elsevier": ProviderConfig()}
        ),
    )
    container = ServiceContainer(config)
    container.acquisition.oa_fetcher = OpenAccessFetcher(
        transport=httpx.MockTransport(oa_transport)
    )
    container.acquisition.resolver.oa_lookup = lambda doi, refresh=False: __import__(
        "lit_harvest.services.resolver", fromlist=["OAResult"]
    ).OAResult(
        doi=doi,
        is_oa=True,
        downloadable=True,
        pdf_url="https://example.org/oa.pdf",
        source="openalex",
    )

    class Publisher:
        name = "elsevier"
        display_name = "Elsevier"
        supports_fulltext = True
        fulltext_service = "article_retrieval"

        def fetch_fulltext(self, doi):
            calls["publisher"] += 1
            raise AssertionError("publisher must not be used when an OA copy exists")

    container.providers.register(Publisher())
    container.acquisition.providers = container.providers

    result = container.acquisition.fetch_now("10.1000/oa")
    assert calls["oa"] == 1
    assert calls["publisher"] == 0
    assert Path(result.raw_path).name == "openaccess.pdf"
    assert result.raw_path.endswith("openaccess.pdf")


# ------------------------------------------------------------- credential pool


def pool_for(tmp_path: Path) -> CredentialPoolService:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": ProviderConfig()}),
    )
    container = ServiceContainer(config)
    container.credentials.secrets = SecretStore(home=tmp_path / "secrets")
    return CredentialPoolService(container.credentials, container.credentials.secrets)


def test_pool_adds_credential_and_stores_secret(tmp_path: Path) -> None:
    pool = pool_for(tmp_path)
    entry = pool.add(
        provider="elsevier",
        name="primary",
        secret="super-secret-key",
        institution="HIT",
        quota_scope="institution",
    )
    assert entry.secret_available is True
    assert entry.institution == "HIT"
    # The API representation must never carry the secret itself.
    assert "super-secret-key" not in str(entry.to_dict())


def test_pool_rejects_credential_without_secret(tmp_path: Path) -> None:
    pool = pool_for(tmp_path)
    with pytest.raises(PoolError, match="No secret was provided"):
        pool.add(provider="elsevier", name="missing", secret=None)


def test_pool_lists_multiple_credentials(tmp_path: Path) -> None:
    pool = pool_for(tmp_path)
    pool.add(provider="elsevier", name="a", secret="k1")
    pool.add(provider="elsevier", name="b", secret="k2")
    names = {item.name for item in pool.entries("elsevier")}
    assert names == {"a", "b"}


def test_pool_toggle_and_delete(tmp_path: Path) -> None:
    pool = pool_for(tmp_path)
    entry = pool.add(provider="elsevier", name="a", secret="k1")

    disabled = pool.set_enabled(entry.credential_id, False)
    assert disabled.enabled is False

    result = pool.remove(entry.credential_id, delete_secret=True)
    assert result["secret_deleted"] is True
    assert pool.entries("elsevier") == []


def test_pool_removal_keeps_secret_by_default(tmp_path: Path) -> None:
    pool = pool_for(tmp_path)
    entry = pool.add(provider="elsevier", name="a", secret="k1")
    result = pool.remove(entry.credential_id)
    assert result["secret_deleted"] is False


def pool_entries(container: ServiceContainer):
    from lit_harvest.services.credential_pool import CredentialPoolService

    return CredentialPoolService(container.credentials, container.credentials.secrets).entries(
        "elsevier"
    )


def test_pool_prefers_least_recently_used(tmp_path: Path) -> None:
    """Two healthy credentials should alternate, not exhaust one."""
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": ProviderConfig()}),
    )
    container = ServiceContainer(config)
    secrets = SecretStore(home=tmp_path / "secrets")
    container.credentials.secrets = secrets
    for name in ("alpha", "beta"):
        secrets.set(f"file:elsevier:{name}", f"key-{name}")
        container.database.upsert_credential(
            provider="elsevier", name=name, secret_ref=f"file:elsevier:{name}", priority=100
        )

    first = container.credentials.select("elsevier", "article_retrieval")
    second = container.credentials.select("elsevier", "article_retrieval")
    third = container.credentials.select("elsevier", "article_retrieval")

    assert first.name != second.name, "pool should rotate across idle credentials"
    assert third.name == first.name, "after one full cycle the first credential is idle again"

    # Usage counters are persisted, so re-read them from the pool.
    counts = {item.name: item.use_count for item in pool_entries(container)}
    assert counts[first.name] == 2
    assert counts[second.name] == 1


def test_pool_skips_disabled_and_missing_secrets(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": ProviderConfig()}),
    )
    container = ServiceContainer(config)
    secrets = SecretStore(home=tmp_path / "secrets")
    container.credentials.secrets = secrets

    secrets.set("file:elsevier:good", "k")
    container.database.upsert_credential(
        provider="elsevier", name="good", secret_ref="file:elsevier:good"
    )
    container.database.upsert_credential(
        provider="elsevier", name="disabled", secret_ref="file:elsevier:disabled", enabled=False
    )
    container.database.upsert_credential(
        provider="elsevier", name="nokey", secret_ref="file:elsevier:nokey"
    )

    chosen = container.credentials.select("elsevier", "article_retrieval")
    assert chosen.name == "good"


def test_selection_preview_does_not_consume_credential(tmp_path: Path) -> None:
    pool = pool_for(tmp_path)
    pool.add(provider="elsevier", name="a", secret="k1")
    preview = pool.selection_preview("elsevier", "article_retrieval")
    assert preview["eligible"] is True
    assert preview["selected"]["name"] == "a"
    # Peeking must not change usage counters.
    assert pool.entries("elsevier")[0].use_count == 0


# ----------------------------------------------------------------------- API


def api_client(tmp_path: Path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": ProviderConfig()}),
    )
    return TestClient(create_app(config, start_worker=False))


def test_credentials_api_never_returns_secret(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    created = client.post(
        "/api/credentials",
        json={
            "provider": "elsevier",
            "name": "primary",
            "secret": "top-secret",
            "institution": "HIT",
        },
    )
    assert created.status_code == 200
    assert "top-secret" not in created.text

    listed = client.get("/api/credentials")
    assert listed.status_code == 200
    assert "top-secret" not in listed.text
    assert listed.json()[0]["secret_available"] is True


def test_credentials_api_rejects_missing_secret(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    response = client.post("/api/credentials", json={"provider": "elsevier", "name": "x"})
    assert response.status_code == 422


def test_credentials_api_toggle_delete_and_health(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    created = client.post(
        "/api/credentials",
        json={"provider": "elsevier", "name": "primary", "secret": "k"},
    ).json()

    toggled = client.post(
        f"/api/credentials/{created['credential_id']}/enabled", json={"enabled": False}
    )
    assert toggled.json()["enabled"] is False

    health = client.get("/api/credentials/elsevier/health")
    assert health.status_code == 200
    assert health.json()["credentials"][0]["eligible"] is False

    deleted = client.delete(f"/api/credentials/{created['credential_id']}")
    assert deleted.status_code == 200
    assert client.get("/api/credentials").json() == []


def test_selection_endpoint_explains_choice(tmp_path: Path) -> None:
    client = api_client(tmp_path)
    client.post("/api/credentials", json={"provider": "elsevier", "name": "primary", "secret": "k"})
    preview = client.get("/api/credentials/elsevier/selection")
    assert preview.status_code == 200
    assert preview.json()["selected"]["name"] == "primary"


def test_oa_candidates_expose_free_access_flag() -> None:
    """Free-access routes are flagged so the UI can show them differently."""
    from lit_harvest.services.resolver import CandidateSource

    source = CandidateSource(
        provider="openalex",
        service="oa_download",
        format="pdf",
        quality=150,
        free_access=True,
        license="cc-by",
    )
    payload = source.to_dict()
    assert payload["free_access"] is True
    assert payload["license"] == "cc-by"


def test_parse_work_handles_null_primary_location() -> None:
    """OpenAlex sometimes returns `primary_location: null`."""
    from lit_harvest.providers.openalex.parser import parse_work

    paper = parse_work(
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/x",
            "primary_location": None,
            "best_oa_location": None,
            "open_access": None,
            "authorships": None,
        }
    )
    assert paper.doi == "10.1000/x"
    assert paper.journal is None
    assert paper.publisher is None
    assert paper.extra["open_access"]["is_oa"] is None


def test_search_results_prime_the_oa_cache(tmp_path: Path) -> None:
    """Search payloads carry OA data, so fetch time needs no extra request."""
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"openalex": OpenAlexConfig()}),
    )
    container = ServiceContainer(config)
    handler = lambda request: httpx.Response(  # noqa: E731
        200, json={"meta": {"count": 1}, "results": [OA_WORK]}
    )
    container.providers.register(openalex_with(handler, container.database))
    container.acquisition.providers = container.providers
    from lit_harvest.services.resolver import Resolver

    container.acquisition.resolver = Resolver(container.providers)

    container.acquisition.search("oa", max_results=1)

    # The lookup must be served from cache: no second network call happens.
    oa = container.acquisition.resolver.oa_lookup("10.1000/oa")
    assert oa.checked is True
    assert oa.downloadable is True
    assert oa.pdf_url == "https://example.org/paper.pdf"
