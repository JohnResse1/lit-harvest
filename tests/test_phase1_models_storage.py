from datetime import UTC, datetime
from pathlib import Path

import pytest

from lit_harvest.models import (
    JobCreate,
    JobStatus,
    PaperCreate,
    PaperDocument,
    PaperIdentifiers,
    QuotaScope,
    QuotaSource,
    QuotaUpdate,
    TaskType,
)
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import (
    DocumentStorage,
    atomic_write_json,
    filesystem_safe_doi,
    normalize_doi,
)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


def test_normalize_and_safe_doi() -> None:
    variants = [
        " 10.1016/J.XXX.2026.1 ",
        "doi:10.1016/J.XXX.2026.1",
        "https://doi.org/10.1016/J.XXX.2026.1",
        "http://dx.doi.org/10.1016/J.XXX.2026.1",
    ]
    assert {normalize_doi(item) for item in variants} == {"10.1016/j.xxx.2026.1"}
    assert filesystem_safe_doi("10.1016/j.mtcomm.2026.115551") == "10.1016_j.mtcomm.2026.115551"
    assert "/" not in filesystem_safe_doi("10.1000/a/b")


def test_atomic_json_write(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state.json"
    atomic_write_json(path, {"ok": True})
    assert path.read_text(encoding="utf-8") == '{\n  "ok": true\n}\n'
    assert not list(path.parent.glob(".*.state.json.*"))


def test_document_storage_layout(tmp_path: Path) -> None:
    storage = DocumentStorage(tmp_path)
    raw = storage.write_raw("10.1016/j.xxx", "science_direct.xml", b"<xml/>")
    normalized = storage.write_normalized("10.1016/j.xxx", {"bibliographic": {"title": "T"}})
    state = storage.write_state("10.1016/j.xxx", {"stage": "downloaded"})
    assert raw == tmp_path / "papers" / "10.1016_j.xxx" / "raw" / "science_direct.xml"
    assert raw.read_bytes() == b"<xml/>"
    assert normalized.exists()
    assert state.exists()
    assert storage.read_normalized("10.1016/j.xxx") == {"bibliographic": {"title": "T"}}
    assert storage.healthcheck()[0] is True


def test_paper_upsert_and_identifier_deduplication(database: Database) -> None:
    first = database.upsert_paper(
        PaperCreate(
            doi="https://doi.org/10.1016/J.XXX",
            title="Initial",
            identifiers=PaperIdentifiers(scopus_id="123", eid="2-s2.0-123"),
        )
    )
    second = database.upsert_paper(
        PaperCreate(
            doi="doi:10.1016/j.xxx",
            title="Updated",
            journal="Journal",
            identifiers=PaperIdentifiers(pii="S0001"),
        )
    )
    assert first.id == second.id
    assert second.doi == "10.1016/j.xxx"
    assert second.title == "Updated"
    assert database.count_papers() == 1
    assert database.get_paper_by_identifier("eid", "2-s2.0-123") is not None


def test_job_lifecycle_and_deduplication(database: Database) -> None:
    paper = database.create_paper(PaperCreate(doi="10.1000/test"))
    created = database.create_job(
        JobCreate(task_type=TaskType.FETCH_FULLTEXT, paper_id=paper.id, provider="elsevier")
    )
    duplicate = database.create_job(
        JobCreate(task_type=TaskType.FETCH_FULLTEXT, paper_id=paper.id, provider="elsevier")
    )
    assert created.id == duplicate.id
    claimed = database.claim_next_job()
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempts == 1
    retried = database.update_job_status(
        claimed.id,
        JobStatus.RETRY,
        error_code="timeout",
        next_retry_at=datetime.now(UTC),
    )
    assert retried.status == JobStatus.RETRY
    assert database.count_jobs(JobStatus.RETRY) == 1
    database.update_job_status(claimed.id, JobStatus.SUCCESS)
    assert database.count_jobs(JobStatus.SUCCESS) == 1


def test_quota_state_and_status(database: Database) -> None:
    update = QuotaUpdate(
        provider="elsevier",
        service="scopus_search",
        credential_id="cred-1",
        limit=20_000,
        remaining=4_000,
        reset_at=datetime(2026, 10, 1, tzinfo=UTC),
        source=QuotaSource.RESPONSE_HEADER,
        quota_scope=QuotaScope.INSTITUTION,
    )
    state = database.upsert_quota(update)
    assert state.status.value == "warning"
    assert database.get_quota("elsevier", "scopus_search", "cred-1") == state
    exhausted = database.upsert_quota(update.model_copy(update={"remaining": 0}))
    assert exhausted.status.value == "exhausted"


def test_paper_document_model_accepts_serialized_payload() -> None:
    document = PaperDocument.model_validate(
        {
            "identifiers": {"doi": "10.1000/x"},
            "bibliographic": {"title": "Title", "journal": "Journal"},
            "provenance": {
                "provider": "elsevier",
                "service": "article_retrieval",
                "format": "xml",
                "parser_version": "1.0",
            },
        }
    )
    payload = document.model_dump(mode="json")
    assert payload["identifiers"]["doi"] == "10.1000/x"
    assert document.counts() == {"sections": 0, "figures": 0, "tables": 0, "references": 0}


def test_upsert_credential_resets_health_when_secret_ref_changes(database: Database) -> None:
    credential_id = database.upsert_credential(
        provider="elsevier",
        name="primary",
        secret_ref="file:elsevier:primary",
    )
    database.set_credential_health(
        credential_id,
        __import__("lit_harvest.models", fromlist=["HealthStatus"]).HealthStatus.UNHEALTHY,
        "bad key",
    )
    database.upsert_credential(
        provider="elsevier",
        name="primary",
        secret_ref="file:elsevier:primary-rotated",
    )
    assert database.get_credential(credential_id)["health_status"] == "unknown"
