from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lit_harvest.config import SchedulerConfig
from lit_harvest.models import (
    JobCreate,
    JobStatus,
    QuotaScope,
    QuotaSource,
    QuotaStatus,
    QuotaUpdate,
    TaskType,
)
from lit_harvest.providers.base import (
    EntitlementError,
    NotFoundError,
    ProviderError,
    RateLimitError,
    TransientProviderError,
)
from lit_harvest.quotas.manager import QuotaManager
from lit_harvest.scheduler.queue import QueueControl
from lit_harvest.scheduler.retry import classify_error, retry_delay
from lit_harvest.scheduler.scheduler import Scheduler
from lit_harvest.storage.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


def add_job(database: Database, task_type: TaskType = TaskType.NORMALIZE) -> str:
    return database.create_job(JobCreate(task_type=task_type)).id


def test_retry_policy() -> None:
    assert retry_delay(1, base_delay_seconds=2) == 2
    assert retry_delay(3, base_delay_seconds=2) == 8
    assert retry_delay(8, base_delay_seconds=2, max_delay_seconds=20) == 20
    assert retry_delay(1, retry_after=30, max_delay_seconds=10) == 10
    assert classify_error(RateLimitError("slow")) == JobStatus.WAITING_FOR_QUOTA
    assert classify_error(TransientProviderError("timeout")) == JobStatus.RETRY
    assert classify_error(EntitlementError("403")) == JobStatus.NOT_ENTITLED
    assert classify_error(NotFoundError("404")) == JobStatus.NOT_FOUND
    assert classify_error(ProviderError("bad")) == JobStatus.RETRY


def test_retryable_job_transitions(database: Database) -> None:
    job_id = add_job(database)
    attempts = 0

    def handler(_job):
        nonlocal attempts
        attempts += 1
        raise TransientProviderError("temporary")

    scheduler = Scheduler(database, config=SchedulerConfig())
    scheduler.register(TaskType.NORMALIZE, handler)
    result = scheduler.run(max_jobs=1)
    assert result.retried == 1
    job = database.get_job(job_id)
    assert job is not None
    assert job.status == JobStatus.RETRY
    assert job.next_retry_at is not None

    # Avoid waiting for backoff: make the retry immediately eligible.
    job.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    with database.session() as session:
        from lit_harvest.storage.database import JobRow

        row = session.get(JobRow, job.id)
        assert row is not None
        row.next_retry_at = job.next_retry_at
        row.max_attempts = 1
    result = scheduler.run(max_jobs=1)
    assert result.failed == 1
    final = database.get_job(job_id)
    assert final is not None
    assert final.status == JobStatus.FAILED


def test_permanent_failures_are_not_retried(database: Database) -> None:
    database.create_job(JobCreate(task_type=TaskType.FETCH_FULLTEXT))
    scheduler = Scheduler(database)
    scheduler.register(
        TaskType.FETCH_FULLTEXT,
        lambda _job: (_ for _ in ()).throw(EntitlementError("403 entitlement")),
    )
    result = scheduler.run(max_jobs=1)
    assert result.failed == 1
    failure = database.list_failures()[0]
    assert failure["status"] == JobStatus.NOT_ENTITLED.value
    assert "403" in failure["error_message"]


def test_pause_and_resume(database: Database) -> None:
    add_job(database)
    scheduler = Scheduler(database, queue_control=QueueControl())
    scheduler.pause("maintenance")
    result = scheduler.run(max_jobs=1)
    assert result.attempted == 0
    assert result.stopped_reason == "maintenance"
    assert database.count_jobs(JobStatus.PENDING) == 1
    scheduler.resume()
    scheduler.register(TaskType.NORMALIZE, lambda _job: {"ok": True})
    assert scheduler.run(max_jobs=1).succeeded == 1
    assert database.count_jobs(JobStatus.SUCCESS) == 1


def test_quota_aware_scheduling(database: Database) -> None:
    database.create_job(
        JobCreate(
            task_type=TaskType.FETCH_FULLTEXT,
            provider="elsevier",
            service="article_retrieval",
            max_attempts=4,
        )
    )
    database.upsert_quota(
        QuotaUpdate(
            provider="elsevier",
            service="article_retrieval",
            limit=1,
            remaining=0,
            reset_at=datetime.now(UTC) + timedelta(hours=1),
            source=QuotaSource.RESPONSE_HEADER,
            quota_scope=QuotaScope.INSTITUTION,
            status=QuotaStatus.EXHAUSTED,
        )
    )
    calls = 0

    def handler(_job):
        nonlocal calls
        calls += 1
        return {}

    scheduler = Scheduler(database, quotas=QuotaManager(database))
    scheduler.register(TaskType.FETCH_FULLTEXT, handler)
    result = scheduler.run(max_jobs=10)
    assert result.waiting_for_quota == 1
    assert calls == 0
    job = database.list_jobs()[0]
    assert job.status == JobStatus.WAITING_FOR_QUOTA
    assert job.error_code == "quota_exhausted"


def test_quota_runway(database: Database) -> None:
    for _ in range(3):
        database.create_job(
            JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                provider="elsevier",
                service="article_retrieval",
            ),
            deduplicate=False,
        )
    database.upsert_quota(
        QuotaUpdate(
            provider="elsevier",
            service="article_retrieval",
            remaining=2,
            source=QuotaSource.RESPONSE_HEADER,
            quota_scope=QuotaScope.INSTITUTION,
        )
    )
    runway = Scheduler(database).quota_runway(provider="elsevier", service="article_retrieval")
    assert runway["queued_jobs"] == 3
    assert runway["remaining"] == 2
    assert runway["sufficient"] is False
    assert runway["shortfall"] == 1
