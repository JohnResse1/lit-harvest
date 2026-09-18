from pathlib import Path

from lit_harvest.config import AppConfig, DatabaseConfig, ProvidersConfig, StorageConfig
from lit_harvest.demo.generator import clear_demo_data, generate_demo_data
from lit_harvest.services.container import ServiceContainer


def container_for(tmp_path: Path) -> ServiceContainer:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    return ServiceContainer(config)


def test_demo_generates_papers_without_credentials(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    # No credentials are configured at all.
    assert container.credentials.list_credentials("elsevier") == []

    result = generate_demo_data(container)

    assert result.created_papers == 3
    assert result.created_jobs == 3
    assert container.database.count_papers() == 3
    assert len(result.files) == 3


def test_demo_writes_raw_and_normalized_files(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    generate_demo_data(container)

    for paper in container.database.list_papers():
        assert paper.doi is not None
        base = container.storage.paper_dir(paper.doi)
        assert (base / "raw" / "elsevier_xml.xml").exists()
        assert (base / "normalized" / "paper.json").exists()
        assert (base / "state.json").exists()


def test_demo_documents_parse_through_real_parser(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    generate_demo_data(container)

    for paper in container.database.list_papers():
        normalized = paper.extra.get("normalized")
        assert normalized, f"demo paper {paper.doi} was not normalized"
        assert normalized["identifiers"]["doi"] == paper.doi
        assert normalized["bibliographic"]["title"]
        assert normalized["abstract"]
        assert normalized["sections"]


def test_demo_is_idempotent(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    first = generate_demo_data(container)
    second = generate_demo_data(container)
    assert first.created_papers == 3
    assert second.created_papers == 0
    assert second.skipped_papers == 3
    assert container.database.count_papers() == 3


def test_demo_records_quota_snapshot(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    generate_demo_data(container)
    quotas = container.database.list_quotas()
    services = {quota.service for quota in quotas}
    assert "scopus_search" in services
    assert "article_retrieval" in services


def test_demo_clear_removes_generated_data(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    generate_demo_data(container)
    assert container.database.count_papers() == 3

    removed = clear_demo_data(container)
    assert removed == 3
    assert container.database.count_papers() == 0

    for paper in container.database.list_papers():
        assert paper.doi is not None
        assert not container.storage.paper_dir(paper.doi).exists()


def test_demo_clear_only_removes_demo_papers(tmp_path: Path) -> None:
    from lit_harvest.models import PaperCreate

    container = container_for(tmp_path)
    container.database.create_paper(PaperCreate(doi="10.1000/real-paper", title="Real"))
    generate_demo_data(container)

    clear_demo_data(container)

    remaining = container.database.list_papers()
    assert len(remaining) == 1
    assert remaining[0].doi == "10.1000/real-paper"


def test_demo_cli_runs_offline(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from lit_harvest.cli import app

    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
storage:
  root: {tmp_path / "data"}
database:
  url: sqlite:///{tmp_path / "state.db"}
providers:
  elsevier:
    credentials: []
""",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--config", str(config)])
    assert result.exit_code == 0
    assert "Demo data ready" in result.stdout

    cleared = runner.invoke(app, ["demo", "--clear", "--config", str(config)])
    assert cleared.exit_code == 0
    assert "Removed 3 demo paper(s)" in cleared.stdout


def test_missing_credential_gives_friendly_error(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from lit_harvest.cli import app

    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
storage:
  root: {tmp_path / "data"}
database:
  url: sqlite:///{tmp_path / "state.db"}
providers:
  elsevier:
    credentials: []
""",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["fetch", "10.1016/j.mtcomm.2026.115551", "--config", str(config)]
    )
    assert result.exit_code == 1
    assert "No Elsevier API key is configured yet" in result.stdout
    assert "Traceback" not in result.stdout
    assert "auth set" in result.stdout
