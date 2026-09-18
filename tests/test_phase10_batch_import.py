from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import AppConfig, DatabaseConfig, ProvidersConfig, StorageConfig
from lit_harvest.models import JobStatus


def client_for(tmp_path: Path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    return TestClient(create_app(config, start_worker=False))


def test_import_returns_exact_paper_ids(tmp_path: Path, monkeypatch) -> None:
    from lit_harvest.services.container import ServiceContainer

    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    container = ServiceContainer(config)
    csv_path = tmp_path / "dois.csv"
    csv_path.write_text(
        "doi\n10.1000/one\nhttps://doi.org/10.1000/two\nbad-doi\n10.1000/one\n",
        encoding="utf-8",
    )
    result = container.acquisition.import_dois(csv_path)
    assert result.queued == 2
    assert len(result.paper_ids) == 2
    assert len(result.queued_paper_ids) == 2
    assert len(result.invalid) == 1
    # The ids must belong to the imported papers, not to unrelated recent rows.
    dois = {container.papers.get(pid).doi for pid in result.paper_ids}
    assert dois == {"10.1000/one", "10.1000/two"}


def test_import_deduplicates_existing_papers(tmp_path: Path) -> None:
    from lit_harvest.services.container import ServiceContainer

    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    container = ServiceContainer(config)
    csv_path = tmp_path / "dois.csv"
    csv_path.write_text("doi\n10.1000/one\n", encoding="utf-8")
    first = container.acquisition.import_dois(csv_path)
    second = container.acquisition.import_dois(csv_path)
    assert first.queued == 1
    assert second.queued == 0
    assert second.duplicates == 1


def test_api_import_accepts_custom_column_and_queues(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.post(
        "/api/papers/import?doi_column=identifier&run_now=false",
        files={
            "file": (
                "dois.csv",
                "identifier,title\n10.1000/api-one,First\ndoi:10.1000/api-two,Second\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["queued"] == 2
    assert len(payload["paper_ids"]) == 2
    assert "run" not in payload


def test_api_import_missing_column_returns_422(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.post(
        "/api/papers/import?doi_column=nonexistent",
        files={"file": ("dois.csv", "doi\n10.1000/x\n", "text/csv")},
    )
    assert response.status_code == 422


def test_api_import_rejects_unsupported_type(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.post(
        "/api/papers/import",
        files={"file": ("dois.xlsx", b"binary", "application/vnd.ms-excel")},
    )
    assert response.status_code == 415


def test_api_import_run_now_executes_jobs(tmp_path: Path, monkeypatch) -> None:
    from lit_harvest.providers.base import FullTextResult

    client = client_for(tmp_path)
    container = client.app.state.container
    xml = (Path(__file__).parent / "fixtures" / "science_direct_full.xml").read_bytes()

    class FakeProvider:
        name = "elsevier"
        display_name = "Elsevier"
        supports_search = True
        supports_fulltext = True
        supports_pdf = False
        supports_metadata = True
        search_service = "scopus_search"
        fulltext_service = "article_retrieval"
        pdf_service = "article_pdf"

        def fetch_fulltext(self, doi: str) -> FullTextResult:
            return FullTextResult(
                doi=doi,
                content=xml,
                content_type="text/xml",
                format="xml",
                http_status=200,
                url=f"https://example.invalid/{doi}",
                provider="elsevier",
                service="article_retrieval",
                credential=None,
            )

        def fetch_pdf(self, doi: str) -> FullTextResult:
            raise RuntimeError("not used")

        def search(self, *args, **kwargs):
            return []

        def healthcheck(self, *args, **kwargs):
            return []

    container.providers.register(FakeProvider())
    container.acquisition.providers = container.providers
    response = client.post(
        "/api/papers/import?run_now=true",
        files={"file": ("dois.csv", "doi\n10.1000/run-one\n", "text/csv")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["attempted"] == 1
    assert payload["run"]["succeeded"] == 1
    assert container.database.count_jobs(JobStatus.SUCCESS) >= 1


def test_sample_files_ship_with_package() -> None:
    root = Path(__file__).parents[1] / "src" / "lit_harvest" / "api" / "examples"
    csv = root / "dois.sample.csv"
    txt = root / "dois.sample.txt"
    assert csv.exists() and txt.exists()
    assert "doi" in csv.read_text(encoding="utf-8").splitlines()[0].lower()


def test_sample_csv_endpoint_returns_csv_not_html(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.get("/api/papers/import/sample.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers.get("content-disposition", "")
    body = response.text
    assert body.startswith("doi,")
    assert "10.1016/" in body
    assert "<!doctype html" not in body.lower()


def test_missing_asset_returns_404_not_html(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    # A missing file-like path must not be masked by the SPA fallback with HTML.
    response = client.get("/assets/does-not-exist.js")
    assert response.status_code == 404
    response = client.get("/examples/does-not-exist.csv")
    assert response.status_code == 404


def test_spa_fallback_still_serves_app_routes(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    response = client.get("/papers")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_minimal_csv_requires_header() -> None:
    import pytest

    from lit_harvest.input.doi_loader import load_dois

    with_header = Path("/tmp/minimal_with_header.csv")
    with_header.write_text("doi\n10.1000/x\n", encoding="utf-8")
    assert [item.doi for item in load_dois(with_header).valid] == ["10.1000/x"]

    without_header = Path("/tmp/minimal_without_header.csv")
    without_header.write_text("10.1000/x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not found"):
        load_dois(without_header)


def test_doi_endpoint_returns_clean_error_for_missing_article(tmp_path: Path, monkeypatch) -> None:
    """Provider payloads must never leak to the browser as raw XML."""
    from lit_harvest.providers.base import NotFoundError

    client = client_for(tmp_path)
    container = client.app.state.container

    class NotFoundProvider:
        name = "elsevier"
        display_name = "Elsevier"
        supports_search = True
        supports_fulltext = True
        supports_pdf = False
        supports_metadata = True
        search_service = "scopus_search"
        fulltext_service = "article_retrieval"
        pdf_service = "article_pdf"

        def fetch_fulltext(self, doi: str):
            raise NotFoundError(
                "<service-error><status><statusCode>RESOURCE_NOT_FOUND</statusCode>"
                "</status></service-error>",
                status_code=404,
            )

        def search(self, *args, **kwargs):
            return []

        def healthcheck(self, *args, **kwargs):
            return []

    container.providers.register(NotFoundProvider())
    container.acquisition.providers = container.providers

    response = client.post(
        "/api/papers/doi",
        json={"doi": "10.1016/j.solidstatesciences.2019.105969", "download_pdf": False},
    )
    assert response.status_code == 404
    body = response.text
    assert "service-error" not in body
    assert "RESOURCE_NOT_FOUND" not in body
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert "could not find this DOI" in detail["message"]


def test_doi_endpoint_maps_entitlement_to_403(tmp_path: Path) -> None:
    from lit_harvest.providers.base import EntitlementError

    client = client_for(tmp_path)
    container = client.app.state.container

    class BlockedProvider:
        name = "elsevier"
        display_name = "Elsevier"
        supports_search = True
        supports_fulltext = True
        supports_pdf = False
        supports_metadata = True
        search_service = "scopus_search"
        fulltext_service = "article_retrieval"
        pdf_service = "article_pdf"

        def fetch_fulltext(self, doi: str):
            raise EntitlementError("not entitled", status_code=403)

        def search(self, *args, **kwargs):
            return []

        def healthcheck(self, *args, **kwargs):
            return []

    container.providers.register(BlockedProvider())
    container.acquisition.providers = container.providers

    response = client.post("/api/papers/doi", json={"doi": "10.1000/blocked"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "not_entitled"
