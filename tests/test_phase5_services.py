from pathlib import Path

import pytest

from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ProvidersConfig,
    SchedulerConfig,
    StorageConfig,
)
from lit_harvest.models import HealthStatus, JobStatus, PaperStage
from lit_harvest.providers.base import FullTextResult, HealthCheckResult, SearchPage
from lit_harvest.services.container import ServiceContainer


class FakeElsevier:
    name = "elsevier"
    display_name = "Elsevier"
    supports_search = True
    supports_fulltext = True
    supports_pdf = True
    supports_metadata = True
    search_service = "scopus_search"
    fulltext_service = "article_retrieval"
    pdf_service = "article_pdf"

    def __init__(self, xml: bytes):
        self.xml = xml
        self.search_calls = 0
        self.fetch_calls = 0

    def search(self, query, *, max_results, start_year=None, end_year=None):
        self.search_calls += 1
        from lit_harvest.models import PaperCreate, PaperIdentifiers

        return [
            SearchPage(
                papers=[
                    PaperCreate(
                        doi="10.1016/j.test.1",
                        title="Test paper",
                        journal="Test Journal",
                        publication_year=2026,
                        identifiers=PaperIdentifiers(doi="10.1016/j.test.1"),
                    )
                ],
                total_results=1,
                start_index=0,
                items_per_page=1,
                current_cursor="*",
                next_cursor=None,
                raw=b'{"search-results": {}}',
            )
        ]

    def healthcheck(self, service=None, *, network=True):
        return [
            HealthCheckResult("elsevier", "scopus_search", HealthStatus.HEALTHY, "mock"),
            HealthCheckResult("elsevier", "article_retrieval", HealthStatus.HEALTHY, "mock"),
        ]

    def fetch_fulltext(self, doi):
        self.fetch_calls += 1
        return FullTextResult(
            doi=doi,
            content=self.xml,
            content_type="text/xml",
            format="xml",
            http_status=200,
            url=f"https://api.elsevier.com/content/article/doi/{doi}",
            provider="elsevier",
            service="article_retrieval",
            credential=None,
        )


@pytest.fixture
def container(tmp_path: Path) -> ServiceContainer:
    xml = (Path(__file__).parent / "fixtures" / "science_direct_full.xml").read_bytes()
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        scheduler=SchedulerConfig(),
        providers=ProvidersConfig(),
    )
    container = ServiceContainer(config)
    container.elsevier = FakeElsevier(xml)
    container.providers.register(container.elsevier)
    container.acquisition.providers = container.providers
    return container


def test_search_stores_papers_and_raw(container: ServiceContainer) -> None:
    result = container.acquisition.search("TITLE-ABS-KEY(test)", max_results=10)
    assert result.discovered == 1
    assert result.stored == 1
    assert Path(result.raw_paths[0]).exists()
    paper = container.papers.by_doi("10.1016/j.test.1")
    assert paper is not None
    assert paper.title == "Test paper"


def test_doi_import_queue_and_fetch(container: ServiceContainer, tmp_path: Path) -> None:
    csv_path = tmp_path / "papers.csv"
    csv_path.write_text(
        "doi\nhttps://doi.org/10.1016/j.test.1\ninvalid\n10.1016/j.test.1\n",
        encoding="utf-8",
    )
    imported = container.acquisition.import_dois(csv_path)
    assert imported.queued == 1
    assert len(imported.invalid) == 1
    assert container.database.count_jobs(JobStatus.PENDING) == 1

    paper = container.papers.by_doi("10.1016/j.test.1")
    assert paper is not None
    result = container.acquisition.fetch_now("10.1016/j.test.1")
    assert result.reused is False
    assert Path(result.raw_path).exists()
    assert result.normalized_path is not None
    assert Path(result.normalized_path).exists()

    # Resume behavior: a second fetch reuses the successful raw file and does not redownload.
    fake = container.elsevier
    reused = container.acquisition.fetch_now("10.1016/j.test.1")
    assert reused.reused is True
    assert fake.fetch_calls == 1

    detailed = container.papers.detail(result.paper_id)
    assert detailed is not None
    assert detailed["parsing"]["references"] == 1
    assert detailed["paper"]["stage"] == PaperStage.NORMALIZED.value


def test_parse_pending_and_export(container: ServiceContainer, tmp_path: Path) -> None:
    imported_path = tmp_path / "papers.txt"
    imported_path.write_text("10.1016/j.test.1\n", encoding="utf-8")
    container.acquisition.import_dois(imported_path)
    result = container.acquisition.fetch_now("10.1016/j.test.1")
    paper = container.papers.get(result.paper_id)
    assert paper is not None
    # Simulate a parser upgrade by clearing normalized metadata while retaining raw data.
    container.database.add_paper_extra(paper.id, {"normalized_path": None})
    parsed = container.acquisition.parse_pending()
    assert parsed["processed"] == 1
    updated = container.papers.get(paper.id)
    assert updated is not None
    assert updated.stage == PaperStage.NORMALIZED.value

    export_path = tmp_path / "papers.csv"
    container.papers.export(export_path)
    assert "10.1016/j.test.1" in export_path.read_text(encoding="utf-8")


def test_dashboard_and_failure_controls(container: ServiceContainer) -> None:
    container.acquisition.search("test", max_results=1)
    overview = container.dashboard.overview()
    assert overview["papers"]["total"] == 1
    assert overview["papers"]["stages"]["discovered"] == 1
    providers = container.dashboard.providers()
    assert providers[0]["name"] == "elsevier"

    container.maintenance.pause("test")
    assert container.dashboard.overview()["queue"]["paused"] is True
    container.maintenance.resume()
    assert container.dashboard.overview()["queue"]["paused"] is False


def test_doctor_offline(container: ServiceContainer) -> None:
    result = container.doctor(network=False)
    assert result["database"]["ok"] is True
    assert result["storage"]["ok"] is True
    assert isinstance(result["providers"], list)


def test_fetch_now_completes_single_job_and_reuses(container: ServiceContainer) -> None:
    first = container.acquisition.fetch_now("10.1016/j.test.1")
    assert first.reused is False
    assert container.database.count_jobs(JobStatus.SUCCESS) == 1
    assert container.database.count_jobs(JobStatus.PENDING) == 0
    second = container.acquisition.fetch_now("10.1016/j.test.1")
    assert second.reused is True
    assert container.database.count_jobs(JobStatus.SUCCESS) == 2


def test_fetch_pdf_saves_attachment_and_reuses(container: ServiceContainer) -> None:
    class FakePdfElsevier(FakeElsevier):
        def __init__(self, xml: bytes, pdf_payload: bytes):
            super().__init__(xml)
            self.pdf_payload = pdf_payload

        def fetch_pdf(self, doi):
            return FullTextResult(
                doi=doi,
                content=self.pdf_payload,
                content_type="application/pdf",
                format="pdf",
                http_status=200,
                url="https://api.elsevier.com/content/article/doi/" + doi,
                provider="elsevier",
                service="article_pdf",
                credential=None,
            )

    container.elsevier = FakePdfElsevier(
        (Path(__file__).parent / "fixtures" / "science_direct_full.xml").read_bytes(),
        b"%PDF-1.7\nservices fake\n%%EOF",
    )
    container.providers.register(container.elsevier)
    container.acquisition.providers = container.providers
    container.acquisition.fetch_now("10.1016/j.test.1")
    paper = container.database.get_paper_by_doi("10.1016/j.test.1")
    assert paper is not None
    first = container.acquisition.fetch_pdf(paper.id)
    assert Path(first["pdf_path"]).read_bytes().startswith(b"%PDF")
    assert first["reused"] is False
    second = container.acquisition.fetch_pdf(paper.id)
    assert second["reused"] is True
