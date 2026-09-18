from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import AppConfig, DatabaseConfig, ProvidersConfig, StorageConfig
from lit_harvest.models import JobStatus
from lit_harvest.providers.base import FullTextResult, SearchPage
from lit_harvest.services.container import ServiceContainer
from lit_harvest.services.search_sessions import SearchCandidate


class FakeSearchProvider:
    name = "elsevier"
    display_name = "Elsevier"

    def __init__(self, xml: bytes):
        self.xml = xml
        self.fetch_calls: list[str] = []

    def search(self, query, *, max_results, start_year=None, end_year=None):
        from lit_harvest.models import PaperCreate, PaperIdentifiers

        return [
            SearchPage(
                papers=[
                    PaperCreate(
                        doi="10.1000/alpha",
                        title="Alpha paper",
                        journal="Journal A",
                        publication_year=2026,
                        document_type="Article",
                        discovery_source="scopus_search",
                        identifiers=PaperIdentifiers(doi="10.1000/alpha", scopus_id="111"),
                        extra={
                            "citation_count": 7,
                            "openaccessFlag": True,
                            "prism:issn": "1234-5678",
                            "prism:volume": "12",
                            "affiliation_text": "Some University",
                        },
                    ),
                    PaperCreate(
                        doi="10.1000/beta",
                        title="Beta paper",
                        journal="Journal B",
                        publication_year=2025,
                        document_type="Review",
                        discovery_source="scopus_search",
                        identifiers=PaperIdentifiers(doi="10.1000/beta", scopus_id="222"),
                        extra={"citation_count": 3, "openaccessFlag": False},
                    ),
                ],
                total_results=2,
                start_index=0,
                items_per_page=2,
                current_cursor="*",
                next_cursor=None,
                raw=b'{"search-results": {}}',
            )
        ]

    def fetch_fulltext(self, doi: str) -> FullTextResult:
        self.fetch_calls.append(doi)
        return FullTextResult(
            doi=doi,
            content=self.xml,
            content_type="text/xml",
            format="xml",
            http_status=200,
            url=f"https://example.invalid/{doi}",
            provider="elsevier",
            service="article_retrieval",
            credential=None,
        )

    def healthcheck(self, *args, **kwargs):
        return []


def build(tmp_path: Path) -> tuple[ServiceContainer, FakeSearchProvider]:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    container = ServiceContainer(config)
    xml = (Path(__file__).parent / "fixtures" / "science_direct_full.xml").read_bytes()
    provider = FakeSearchProvider(xml)
    container.providers.register(provider)
    container.acquisition.providers = container.providers
    return container, provider


def test_search_does_not_download_fulltext(tmp_path: Path) -> None:
    container, provider = build(tmp_path)
    result = container.acquisition.search("test", max_results=10)
    # Search must only register candidates; no full-text retrieval happens.
    assert result.discovered == 2
    assert provider.fetch_calls == []
    assert container.database.count_jobs(JobStatus.SUCCESS) == 0


def test_search_creates_review_session_with_candidates(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    result = container.acquisition.search("test", max_results=10)
    assert result.session_id is not None
    session = container.acquisition.search_sessions.get(result.session_id)
    assert len(session.candidates) == 2
    alpha = next(c for c in session.candidates if c.doi == "10.1000/alpha")
    assert alpha.title == "Alpha paper"
    assert alpha.journal == "Journal A"
    assert alpha.year == 2026
    assert alpha.citation_count == 7
    assert alpha.open_access is True
    assert alpha.issn == "1234-5678"
    assert alpha.volume == "12"
    assert alpha.scopus_id == "111"


def test_selection_persists_and_only_selected_downloads(tmp_path: Path) -> None:
    container, provider = build(tmp_path)
    result = container.acquisition.search("test", max_results=10)
    assert result.session_id
    session = container.acquisition.search_sessions.get(result.session_id)
    beta = next(c for c in session.candidates if c.doi == "10.1000/beta")

    container.acquisition.search_sessions.update_selection(result.session_id, [beta.candidate_id])
    outcome = container.acquisition.fetch_selected(result.session_id)

    assert outcome["requested"] == 1
    assert outcome["succeeded"] == 1
    # Only the ticked paper was downloaded.
    assert provider.fetch_calls == ["10.1000/beta"]


def test_download_without_selection_is_rejected(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    result = container.acquisition.search("test", max_results=10)
    assert result.session_id
    import pytest

    with pytest.raises(ValueError, match="No papers were selected"):
        container.acquisition.fetch_selected(result.session_id)


def test_candidate_to_dict_exposes_metadata() -> None:
    candidate = SearchCandidate(
        candidate_id="c1",
        paper_id="p1",
        doi="10.1000/x",
        title="Title",
        journal="Journal",
        year=2026,
        authors="A; B",
        affiliation="Uni",
        document_type="Article",
        citation_count=5,
        open_access=True,
        free_to_read="All Open Access",
        issn="1234-5678",
        volume="1",
        issue="2",
        pages="1-10",
        cover_date="2026-01-01",
        scopus_id="999",
        eid="2-s2.0-999",
        scopus_url="https://example.invalid",
    )
    payload = candidate.to_dict()
    for key in ("title", "journal", "authors", "citation_count", "open_access", "issn", "eid"):
        assert key in payload


def test_search_api_returns_candidates_and_selection_flow(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    client = TestClient(create_app(config, start_worker=False))
    container = client.app.state.container
    xml = (Path(__file__).parent / "fixtures" / "science_direct_full.xml").read_bytes()
    container.providers.register(FakeSearchProvider(xml))
    container.acquisition.providers = container.providers

    search = client.post("/api/search", json={"query": "test", "max_results": 10})
    assert search.status_code == 200
    payload = search.json()
    assert payload["discovered"] == 2
    assert len(payload["candidates"]) == 2
    session_id = payload["session_id"]
    assert session_id

    beta = next(c for c in payload["candidates"] if c["doi"] == "10.1000/beta")
    selected = client.post(
        f"/api/search/sessions/{session_id}/select",
        json={"candidate_ids": [beta["candidate_id"]]},
    )
    assert selected.status_code == 200
    assert selected.json()["selected_count"] == 1

    downloaded = client.post(
        f"/api/search/sessions/{session_id}/download",
        json={"candidate_ids": [beta["candidate_id"]], "download_pdf": False},
    )
    assert downloaded.status_code == 200
    assert downloaded.json()["succeeded"] == 1

    missing = client.get("/api/search/sessions/does-not-exist")
    assert missing.status_code == 404


def test_selection_failure_message_has_no_raw_provider_xml(tmp_path: Path) -> None:
    """Failure summaries shown in the UI must never contain provider XML."""
    from lit_harvest.providers.base import NotFoundError

    container, _ = build(tmp_path)
    result = container.acquisition.search("test", max_results=10)
    assert result.session_id
    session = container.acquisition.search_sessions.get(result.session_id)
    alpha = next(c for c in session.candidates if c.doi == "10.1000/alpha")

    class FailingProvider:
        name = "elsevier"
        display_name = "Elsevier"

        def fetch_fulltext(self, doi: str):
            raise NotFoundError(
                "<service-error><status><statusCode>RESOURCE_NOT_FOUND</statusCode>"
                "<statusText>The resource specified cannot be found.</statusText>"
                "</status></service-error>",
                status_code=404,
            )

        def search(self, *args, **kwargs):
            return []

        def healthcheck(self, *args, **kwargs):
            return []

    container.providers.register(FailingProvider())
    container.acquisition.providers = container.providers
    # Nothing is selected by default, so tick the candidate explicitly first.
    container.acquisition.search_sessions.update_selection(result.session_id, [alpha.candidate_id])
    outcome = container.acquisition.fetch_selected(result.session_id)

    assert outcome["failed"] == 1
    message = outcome["results"][0]["message"]
    assert "<service-error>" not in message
    assert "RESOURCE_NOT_FOUND" not in message
    assert "could not find this DOI" in message
