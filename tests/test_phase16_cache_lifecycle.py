"""Cleanup and rebuild of the raw full-text cache."""

from pathlib import Path

from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import AppConfig, DatabaseConfig, ProvidersConfig, StorageConfig
from lit_harvest.models import PaperCreate
from lit_harvest.services.container import ServiceContainer


def container_for(tmp_path: Path) -> ServiceContainer:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    return ServiceContainer(config)


def seed_cached_paper(container: ServiceContainer, doi: str = "10.1000/cached") -> str:
    """Create a paper with a raw file and a normalized document on disk."""
    paper = container.database.create_paper(PaperCreate(doi=doi))
    raw = container.storage.write_raw(doi, "elsevier_xml.xml", b"<xml>content</xml>")
    container.storage.write_normalized(doi, {"identifiers": {"doi": doi}})
    container.storage.write_state(doi, {"stage": "normalized"})
    container.database.record_download(
        paper_id=paper.id,
        provider="elsevier",
        service="article_retrieval",
        credential_id=None,
        status="success",
        format="xml",
        raw_path=str(raw),
        checksum=None,
    )
    container.database.add_paper_extra(
        paper.id, {"normalized_path": str(container.storage.normalized_dir(doi) / "paper.json")}
    )
    return paper.id


def test_summary_reports_cached_and_missing(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    seed_cached_paper(container)
    container.database.create_paper(PaperCreate(doi="10.1000/no-cache"))

    summary = container.cache.summary()
    assert summary["papers"] == 2
    assert summary["raw_cached"] == 1
    assert summary["raw_missing"] == 1
    assert summary["normalized_available"] == 1
    assert summary["cached_bytes"] > 0


def test_missing_raw_lists_only_doi_papers_without_files(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    seed_cached_paper(container, "10.1000/has-raw")
    container.database.create_paper(PaperCreate(doi="10.1000/needs-raw"))
    container.database.create_paper(PaperCreate(doi=None))

    targets = container.cache.missing_raw()
    assert [item.doi for item in targets] == ["10.1000/needs-raw"]


def test_cleanup_removes_raw_but_keeps_metadata_and_normalized(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    doi = "10.1000/cleanup"
    paper_id = seed_cached_paper(container, doi)

    result = container.cache.cleanup_raw()

    assert result.cleaned == 1
    assert result.bytes_freed > 0
    assert not container.storage.raw_dir(doi).exists()
    # Derived data survives so the corpus stays usable.
    assert (container.storage.normalized_dir(doi) / "paper.json").exists()
    assert container.database.get_paper(paper_id) is not None
    updated = container.database.get_paper(paper_id)
    assert updated is not None
    assert updated.extra.get("raw_cached") is False


def test_cleanup_can_also_drop_normalized(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    doi = "10.1000/drop-all"
    seed_cached_paper(container, doi)

    container.cache.cleanup_raw(keep_normalized=False)

    assert not container.storage.raw_dir(doi).exists()
    assert not (container.storage.normalized_dir(doi) / "paper.json").exists()
    # Metadata still survives.
    assert container.database.get_paper_by_doi(doi) is not None


def test_cleanup_skips_papers_without_cache(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    container.database.create_paper(PaperCreate(doi="10.1000/nothing"))
    result = container.cache.cleanup_raw()
    assert result.cleaned == 0
    assert result.skipped == 1


def test_cleanup_can_target_specific_papers(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    first = seed_cached_paper(container, "10.1000/first")
    seed_cached_paper(container, "10.1000/second")

    result = container.cache.cleanup_raw(paper_ids=[first])

    assert result.cleaned == 1
    assert not container.storage.raw_dir("10.1000/first").exists()
    assert container.storage.raw_dir("10.1000/second").exists()


def test_cleanup_keeps_state_file_for_provenance(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    doi = "10.1000/state"
    seed_cached_paper(container, doi)
    container.cache.cleanup_raw()
    assert container.storage.state_path(doi).exists()


def test_rebuild_requires_cache_service(tmp_path: Path) -> None:
    """rebuild_missing must fail loudly rather than silently doing nothing."""
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    container = ServiceContainer(config)
    container.acquisition.cache = None
    import pytest

    with pytest.raises(RuntimeError, match="Cache service is not available"):
        container.acquisition.rebuild_missing(limit=1)


def test_cache_endpoints(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(),
    )
    client = TestClient(create_app(config, start_worker=False))
    container = client.app.state.container
    seed_cached_paper(container)

    status = client.get("/api/cache")
    assert status.status_code == 200
    assert status.json()["raw_cached"] == 1

    cleaned = client.post("/api/cache/cleanup")
    assert cleaned.status_code == 200
    assert cleaned.json()["cleaned"] == 1

    after = client.get("/api/cache").json()
    assert after["raw_cached"] == 0
    assert after["raw_missing"] == 1
