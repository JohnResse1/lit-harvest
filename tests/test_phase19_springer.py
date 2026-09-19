"""Springer Nature provider: Meta API and OpenAccess API."""

from pathlib import Path

import httpx
import pytest

from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ProvidersConfig,
    SpringerConfig,
    StorageConfig,
)
from lit_harvest.credentials.store import SecretStore
from lit_harvest.models import HealthStatus
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.springer.parser import (
    extract_urls,
    flatten_abstract,
    parse_springer_record,
    parse_springer_response,
)
from lit_harvest.providers.springer.provider import SpringerProvider
from lit_harvest.services.container import ServiceContainer
from lit_harvest.storage.database import Database

META_RECORD = {
    "doi": "10.1007/s41748-026-01198-0",
    "identifier": "doi:10.1007/s41748-026-01198-0",
    "title": "Sustainable Management of Industrial Waste",
    "publicationName": "Earth Systems and Environment",
    "publicationDate": "2026-12-01",
    "publisherName": "Springer International Publishing",
    "contentType": "Article",
    "openaccess": "true",
    "creators": [
        {"creator": "Carazeanu Popovici, Ionela"},
        {"creator": "Soceanu, Alina", "ORCID": "0000-0002-4617-7800"},
    ],
    "abstract": "A study of chromium remediation.",
    "url": [
        {"format": "html", "value": "https://link.springer.com/article/10.1007/x"},
        {"format": "pdf", "value": "https://link.springer.com/content/pdf/10.1007/x.pdf"},
    ],
    "keyword": ["adsorption", "chromium"],
    "volume": "10",
    "number": "2",
    "startingPage": "100",
    "endingPage": "115",
    "issn": "2509-9426",
}


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


# ------------------------------------------------------------------- parsing


def test_extract_urls_picks_pdf_and_html() -> None:
    urls = extract_urls(META_RECORD)
    assert urls["pdf"] == "https://link.springer.com/content/pdf/10.1007/x.pdf"
    assert urls["html"] == "https://link.springer.com/article/10.1007/x"


def test_extract_urls_tolerates_missing_list() -> None:
    assert extract_urls({}) == {"pdf": None, "html": None, "landing": None}


def test_flatten_abstract_handles_string_and_mapping() -> None:
    assert flatten_abstract("plain text") == "plain text"
    assert flatten_abstract(None) is None
    # The OpenAccess API returns structured abstracts.
    text = flatten_abstract({"h1": "Highlights", "p": "Key finding here"})
    assert "Highlights:" in text
    assert "Key finding here" in text


def test_flatten_abstract_handles_nested_lists() -> None:
    text = flatten_abstract([{"p": "first"}, {"p": "second"}])
    assert text == "first second"


def test_parse_record_maps_core_fields() -> None:
    paper = parse_springer_record(META_RECORD)
    assert paper.doi == "10.1007/s41748-026-01198-0"
    assert paper.title == "Sustainable Management of Industrial Waste"
    assert paper.journal == "Earth Systems and Environment"
    assert paper.publication_year == 2026
    assert paper.publisher == "Springer International Publishing"
    assert paper.discovery_source == "springer"
    assert paper.extra["author_count"] == 2
    assert paper.extra["open_access"]["is_oa"] is True
    assert paper.extra["open_access"]["pdf_url"].endswith(".pdf")
    assert paper.extra["keywords"] == ["adsorption", "chromium"]
    assert paper.extra["volume"] == "10"


def test_parse_record_accepts_boolean_openaccess() -> None:
    record = dict(META_RECORD, openaccess=True)
    assert parse_springer_record(record).extra["open_access"]["is_oa"] is True
    record = dict(META_RECORD, openaccess=False)
    assert parse_springer_record(record).extra["open_access"]["is_oa"] is False


def test_parse_record_handles_openaccess_camel_case() -> None:
    """The OpenAccess API spells it `openAccess`."""
    record = dict(META_RECORD)
    del record["openaccess"]
    record["openAccess"] = True
    assert parse_springer_record(record).extra["open_access"]["is_oa"] is True


def test_closed_access_record_has_no_pdf_target() -> None:
    record = dict(META_RECORD, openaccess=False)
    paper = parse_springer_record(record)
    assert paper.extra["open_access"]["is_oa"] is False
    # A paywalled record must not advertise a downloadable PDF.
    assert paper.extra["open_access"]["pdf_url"] is None


def test_parse_response_reads_paging_metadata() -> None:
    papers, info = parse_springer_response(
        {
            "result": [{"total": "79324", "start": "1", "pageLength": "5"}],
            "records": [META_RECORD],
        }
    )
    assert len(papers) == 1
    assert info["total_results"] == 79324
    assert info["start"] == 1


# ------------------------------------------------------------------ provider


def provider_for(database: Database, handler, tmp_path: Path) -> SpringerProvider:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"springer": SpringerConfig()}),
    )
    container = ServiceContainer(config)
    container.credentials.secrets = SecretStore(home=tmp_path / "secrets")
    for name, service in (
        ("meta", "springer_meta"),
        ("openaccess", "springer_openaccess"),
    ):
        container.credentials.secrets.set(f"file:springer:{name}", f"key-{name}")
        container.database.upsert_credential(
            provider="springer",
            name=name,
            secret_ref=f"file:springer:{name}",
            services=[service],
        )
    client = JsonHttpClient(
        base_url="https://api.springernature.com",
        provider="springer",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    return SpringerProvider(
        database=container.database,
        credentials=container.credentials,
        client=client,
    )


def test_search_sends_paging_and_api_key(database: Database, tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={"result": [{"total": "1", "pageLength": "1"}], "records": [META_RECORD]},
        )

    provider = provider_for(database, handler, tmp_path)
    pages = provider.search("battery", max_results=1)

    assert len(pages) == 1
    assert seen[0]["p"] == "1"
    assert seen[0]["s"] == "1"
    # The Meta credential must supply the key.
    assert seen[0]["api_key"] == "key-meta"


def test_search_adds_year_filter_only_when_requested(database: Database, tmp_path: Path) -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.params.get("q", ""))
        return httpx.Response(200, json={"result": [{}], "records": []})

    provider = provider_for(database, handler, tmp_path)
    provider.search("battery", max_results=1)
    assert captured[0] == "battery"

    provider.search("battery", max_results=1, start_year=2020, end_year=2024)
    assert "datewithin:2020-01-01 2024-12-31" in captured[1]


def test_oa_lookup_uses_meta_api_for_pdf_link(database: Database, tmp_path: Path) -> None:
    """The OpenAccess API lacks PDF URLs, so the Meta API must be tried first."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"result": [{}], "records": [META_RECORD]})

    provider = provider_for(database, handler, tmp_path)
    result = provider.fetch_oa_location("10.1007/s41748-026-01198-0")

    assert result is not None
    assert result["downloadable"] is True
    assert result["pdf_url"].endswith(".pdf")
    assert calls[0] == "/meta/v2/json"


def test_oa_lookup_returns_none_for_closed_access(database: Database, tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"result": [{}], "records": [dict(META_RECORD, openaccess=False)]}
        )

    provider = provider_for(database, handler, tmp_path)
    assert provider.fetch_oa_location("10.1007/closed") is None


def test_credential_allowlist_pairs_each_service_with_its_key(
    database: Database, tmp_path: Path
) -> None:
    """Separate keys per API must not be used interchangeably."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": [{}], "records": [META_RECORD]})

    provider = provider_for(database, handler, tmp_path)
    meta = provider.credentials.peek("springer", "springer_meta")
    oa = provider.credentials.peek("springer", "springer_openaccess")
    assert meta.name == "meta"
    assert oa.name == "openaccess"


def test_fetch_metadata_by_doi(database: Database, tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "doi:10.1007/s41748-026-01198-0" in request.url.params.get("q", "")
        return httpx.Response(200, json={"result": [{}], "records": [META_RECORD]})

    provider = provider_for(database, handler, tmp_path)
    payload = provider.fetch_metadata("https://doi.org/10.1007/s41748-026-01198-0")
    assert payload is not None
    assert payload["title"] == "Sustainable Management of Industrial Waste"


def test_metadata_lookup_returns_none_when_absent(database: Database, tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": [{}], "records": []})

    provider = provider_for(database, handler, tmp_path)
    assert provider.fetch_metadata("10.1007/missing") is None


def test_provider_declares_expected_capabilities() -> None:
    assert SpringerProvider.supports_search is True
    assert SpringerProvider.supports_metadata is True
    assert SpringerProvider.supports_oa_lookup is True
    # Springer serves no publisher full text through this API surface.
    assert SpringerProvider.supports_fulltext is False
    assert SpringerProvider.supports_pdf is False


def test_healthcheck_marks_unhealthy_on_auth_failure(database: Database, tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Authentication failed"})

    provider = provider_for(database, handler, tmp_path)
    results = provider.healthcheck(network=True)
    assert all(item.status == HealthStatus.UNHEALTHY for item in results)


def test_healthcheck_offline_reports_credential_presence(
    database: Database, tmp_path: Path
) -> None:
    provider = provider_for(database, lambda request: httpx.Response(200, json={}), tmp_path)
    results = provider.healthcheck(network=False)
    assert {item.service for item in results} == {"springer_meta", "springer_openaccess"}
    assert all(item.status == HealthStatus.HEALTHY for item in results)


# ----------------------------------------------------------------- container


def test_container_registers_springer_when_enabled(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"springer": SpringerConfig()}),
    )
    container = ServiceContainer(config)
    assert "springer" in container.providers.names()
    # Metadata-capable but not a full-text source.
    assert any(
        p.name == "springer" for p in container.providers.with_capability("supports_oa_lookup")
    )
