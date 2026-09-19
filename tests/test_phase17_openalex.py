"""OpenAlex: key-free cross-publisher discovery and metadata enrichment."""

from pathlib import Path

import httpx
import pytest

from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    OpenAlexConfig,
    ProvidersConfig,
    StorageConfig,
)
from lit_harvest.models import PaperCreate
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.openalex.parser import (
    parse_search_response,
    parse_work,
    reconstruct_abstract,
    strip_doi,
    strip_openalex_id,
)
from lit_harvest.providers.openalex.provider import OpenAlexProvider
from lit_harvest.services.container import ServiceContainer
from lit_harvest.storage.database import Database

SAMPLE_WORK = {
    "id": "https://openalex.org/W7165002001",
    "doi": "https://doi.org/10.1016/j.mtcomm.2026.115551",
    "title": "Information extraction for materials science",
    "publication_year": 2026,
    "type": "article",
    "cited_by_count": 12,
    "language": "en",
    "is_retracted": False,
    "primary_location": {
        "source": {
            "display_name": "Materials Today Communications",
            "issn_l": "2352-4928",
            "host_organization_name": "Elsevier BV",
        }
    },
    "open_access": {
        "is_oa": True,
        "oa_status": "hybrid",
        "oa_url": "https://doi.org/10.1016/j.mtcomm.2026.115551",
    },
    "best_oa_location": {"pdf_url": "https://example.org/a.pdf", "license": "cc-by"},
    "authorships": [
        {
            "author": {"display_name": "Yutong Duan", "orcid": "https://orcid.org/0000-0001"},
            "institutions": [{"display_name": "Harbin Institute of Technology"}],
            "countries": ["CN"],
        },
        {
            "author": {"display_name": "Ying Zhang"},
            "institutions": [],
            "countries": [{"country_code": "CN"}],
        },
    ],
    "biblio": {"volume": "54", "issue": "1", "first_page": "115551", "last_page": "115570"},
    "abstract_inverted_index": {
        "Materials": [0],
        "science": [1],
        "needs": [2],
        "structure": [3],
    },
    "concepts": [{"display_name": "Materials science"}],
    "referenced_works": ["https://openalex.org/W1", "https://openalex.org/W2"],
}


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


# ------------------------------------------------------------------- parsing


def test_strip_helpers() -> None:
    assert strip_doi("https://doi.org/10.1/x") == "10.1/x"
    assert strip_doi("doi:10.1/x") == "10.1/x"
    assert strip_doi("10.1/x") == "10.1/x"
    assert strip_openalex_id("https://openalex.org/W123") == "W123"
    assert strip_openalex_id(None) is None


def test_reconstruct_abstract_orders_words() -> None:
    text = reconstruct_abstract({"b": [1], "a": [0], "c": [2]})
    assert text == "a b c"
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_parse_work_maps_all_key_fields() -> None:
    paper = parse_work(SAMPLE_WORK)
    assert paper.doi == "10.1016/j.mtcomm.2026.115551"
    assert paper.title == "Information extraction for materials science"
    assert paper.journal == "Materials Today Communications"
    assert paper.publication_year == 2026
    assert paper.publisher == "Elsevier BV"
    assert paper.document_type == "article"
    assert paper.discovery_source == "openalex"
    assert paper.identifiers.openalex_id == "W7165002001"

    extra = paper.extra
    assert extra["author_count"] == 2
    assert extra["citation_count"] == 12
    assert extra["abstract"] == "Materials science needs structure"
    assert extra["open_access"]["is_oa"] is True
    assert extra["open_access"]["pdf_url"] == "https://example.org/a.pdf"
    assert extra["volume"] == "54"
    assert extra["referenced_works_count"] == 2
    assert extra["concepts"] == ["Materials science"]


def test_parse_work_handles_missing_fields() -> None:
    paper = parse_work({"id": "https://openalex.org/W1"})
    assert paper.doi is None
    assert paper.title is None
    assert paper.extra["author_count"] == 0


def test_parse_work_accepts_countries_as_strings_and_objects() -> None:
    paper = parse_work(SAMPLE_WORK)
    countries = [author["countries"] for author in paper.extra["authors"]]
    assert countries[0] == ["CN"]
    assert countries[1] == ["CN"]


def test_parse_search_response_reads_meta() -> None:
    papers, info = parse_search_response(
        {"meta": {"count": 404227, "page": 1, "per_page": 3}, "results": [SAMPLE_WORK]}
    )
    assert len(papers) == 1
    assert info["total_results"] == 404227
    assert info["page"] == 1


# ------------------------------------------------------------------ provider


def provider_with(handler, database: Database) -> OpenAlexProvider:
    client = JsonHttpClient(
        base_url="https://api.openalex.org",
        provider="openalex",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    return OpenAlexProvider(database=database, client=client, contact_email="test@example.com")


def test_search_sends_paging_and_polite_pool(database: Database) -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={"meta": {"count": 1, "per_page": 1}, "results": [SAMPLE_WORK]},
        )

    provider = provider_with(handler, database)
    provider.search("battery", max_results=1)

    assert seen[0]["per-page"] == "1"
    assert seen[0]["page"] == "1"
    assert seen[0]["mailto"] == "test@example.com"


def test_search_paginates_until_max_results(database: Database) -> None:
    """Small page size forces the paging loop to run more than once."""
    pages_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        pages_seen.append(page)
        results = [dict(SAMPLE_WORK, id=f"https://openalex.org/W{page}{i}") for i in range(2)]
        return httpx.Response(200, json={"meta": {"count": 10}, "results": results})

    provider = provider_with(handler, database)
    provider.MAX_PAGE_SIZE = 2  # type: ignore[misc]
    pages = provider.search("battery", max_results=4)
    assert pages_seen == [1, 2]
    assert sum(len(page.papers) for page in pages) == 4


def test_search_applies_year_filter(database: Database) -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.params.get("filter", ""))
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    provider = provider_with(handler, database)
    provider.search("x", max_results=1, start_year=2020, end_year=2024)
    assert "from_publication_date:2020-01-01" in captured[0]
    assert "to_publication_date:2024-12-31" in captured[0]


def test_fetch_metadata_returns_normalized_payload(database: Database) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "doi:10.1016/j.mtcomm.2026.115551" in str(request.url)
        return httpx.Response(200, json=SAMPLE_WORK)

    provider = provider_with(handler, database)
    payload = provider.fetch_metadata("https://doi.org/10.1016/j.mtcomm.2026.115551")
    assert payload is not None
    assert payload["title"] == "Information extraction for materials science"
    assert payload["extra"]["author_count"] == 2


def test_provider_declares_metadata_only_capabilities() -> None:
    assert OpenAlexProvider.supports_search is True
    assert OpenAlexProvider.supports_metadata is True
    assert OpenAlexProvider.supports_fulltext is False
    assert OpenAlexProvider.supports_pdf is False


def test_healthcheck_reports_both_services(database: Database) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    provider = provider_with(handler, database)
    results = provider.healthcheck(network=True)
    assert {item.service for item in results} == {"works_search", "works_lookup"}
    assert all(item.status.value == "healthy" for item in results)


# ----------------------------------------------------------------- container


def test_default_config_enables_openalex_without_credentials(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    container = ServiceContainer(config)
    assert "openalex" in container.providers.names()
    # No credential is required, so it is usable immediately.
    metadata_providers = container.providers.with_capability("supports_metadata")
    assert any(p.name == "openalex" for p in metadata_providers)


def test_openalex_does_not_serve_fulltext(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={
                "elsevier": {"enabled": False},
                "openalex": OpenAlexConfig(),
            }
        ),
    )
    container = ServiceContainer(config)
    assert container.providers.fulltext_providers() == []
    # Metadata-only provider must not be chosen as a full-text route.
    assert container.acquisition.resolver.best("10.1000/x") is None


# ---------------------------------------------------------------- enrichment


def test_enrich_fills_missing_title(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"openalex": OpenAlexConfig()}),
    )
    container = ServiceContainer(config)
    paper = container.database.create_paper(
        PaperCreate(doi="10.1016/j.mtcomm.2026.115551", discovery_source="single_doi")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_WORK)

    container.providers.register(provider_with(handler, container.database))
    container.acquisition.providers = container.providers

    result = container.acquisition.enrich_metadata()

    assert result["enriched"] == 1
    updated = container.database.get_paper(paper.id)
    assert updated is not None
    assert updated.title == "Information extraction for materials science"
    assert updated.journal == "Materials Today Communications"
    assert updated.extra["author_count"] == 2


def test_enrich_skips_papers_that_already_have_titles(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"openalex": OpenAlexConfig()}),
    )
    container = ServiceContainer(config)
    container.database.create_paper(
        PaperCreate(doi="10.1000/x", title="Already known", discovery_source="scopus_search")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call the API when a title exists")

    container.providers.register(provider_with(handler, container.database))
    container.acquisition.providers = container.providers

    result = container.acquisition.enrich_metadata(only_incomplete=True)
    assert result["enriched"] == 0
    assert result["skipped"] == 1


def test_enrich_without_metadata_provider_raises(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": {"enabled": True}}),
    )
    container = ServiceContainer(config)
    from lit_harvest.providers.base import ProviderUnavailableError

    with pytest.raises(ProviderUnavailableError, match="No metadata provider"):
        container.acquisition.enrich_metadata()


def test_load_config_adds_openalex_to_a_legacy_file(tmp_path: Path) -> None:
    """An existing config.yaml keeps working and gains key-free discovery."""
    from lit_harvest.config import load_config

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"""
storage:
  root: {tmp_path / "data"}
database:
  url: sqlite:///{tmp_path / "data/lit_harvest.db"}
providers:
  elsevier:
    enabled: true
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.providers.names() == ["elsevier", "openalex"]
    assert config.providers.get("elsevier").enabled is True


def test_user_can_disable_openalex(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={
                "elsevier": {"enabled": True},
                "openalex": {"enabled": False},
            }
        ),
    )
    container = ServiceContainer(config)
    assert "openalex" not in container.providers.names()
