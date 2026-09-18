"""Job scheduler that respects quota, retries, and permanent failures."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from lit_harvest.config import SchedulerConfig
from lit_harvest.models import Job, JobStatus, QuotaScope, QuotaState, QuotaStatus, TaskType
from lit_harvest.providers.base import ProviderError
from lit_harvest.quotas.manager import QuotaManager
from lit_harvest.scheduler.queue import QueueControl
from lit_harvest.scheduler.retry import classify_error, next_retry_at
from lit_harvest.storage.database import Database

logger = logging.getLogger(__name__)

JobHandler = Callable[[Job], dict[str, Any] | None]


@dataclass(slots=True)
class SchedulerRunResult:
    attempted: int = 0
    succeeded: int = 0
    retried: int = 0
    waiting_for_quota: int = 0
    failed: int = 0
    blocked: int = 0
    skipped: int = 0
    stopped_reason: str | None = None
    details: list[dict[str, Any]] = field(default_factory=list)


class Scheduler:
    def __init__(
        self,
        database: Database,
        *,
        config: SchedulerConfig | None = None,
        quotas: QuotaManager | None = None,
        queue_control: QueueControl | None = None,
    ) -> None:
        self.database = database
        self.config = config or SchedulerConfig()
        self.quotas = quotas or QuotaManager(database)
        self.queue = queue_control or QueueControl()
        self.handlers: dict[TaskType, JobHandler] = {}

    def register(self, task_type: TaskType, handler: JobHandler) -> None:
        self.handlers[task_type] = handler

    def pause(self, reason: str | None = None) -> None:
        self.queue.pause(reason)

    def resume(self) -> None:
        self.queue.resume()

    def run_once(self, *, task_types: list[TaskType] | None = None) -> Job | None:
        result = self.run(max_jobs=1, task_types=task_types)
        if not result.details:
            return None
        job_id = result.details[-1].get("job_id")
        return self.database.get_job(str(job_id)) if job_id else None

    def run(
        self,
        *,
        max_jobs: int = 100,
        task_types: list[TaskType] | None = None,
    ) -> SchedulerRunResult:
        result = SchedulerRunResult()
        if self.queue.paused:
            result.stopped_reason = self.queue.reason or "queue paused"
            return result
        for _ in range(max_jobs):
            job = self.database.claim_next_job(task_types=task_types)
            if job is None:
                result.stopped_reason = "queue empty"
                break
            result.attempted += 1
            outcome = self._execute(job)
            result.details.append(outcome)
            status = outcome["status"]
            if status == JobStatus.SUCCESS.value:
                result.succeeded += 1
            elif status == JobStatus.RETRY.value:
                result.retried += 1
            elif status == JobStatus.WAITING_FOR_QUOTA.value:
                result.waiting_for_quota += 1
                # Avoid scanning through the same quota-blocked job repeatedly.
                break
            elif status == JobStatus.BLOCKED.value:
                result.blocked += 1
            else:
                result.failed += 1
        else:
            result.stopped_reason = "max_jobs reached"
        return result

    def _execute(self, job: Job) -> dict[str, Any]:
        handler = self.handlers.get(job.task_type)
        if handler is None:
            self.database.update_job_status(
                job.id,
                JobStatus.BLOCKED,
                error_code="handler_missing",
                error_message=f"No scheduler handler registered for {job.task_type.value}",
            )
            return {"job_id": job.id, "status": JobStatus.BLOCKED.value}

        quota = self._quota_for(job)
        if quota and quota.status in {QuotaStatus.EXHAUSTED, QuotaStatus.COOLDOWN}:
            reset = quota.reset_at
            if reset is None or reset > datetime.now(UTC):
                status = (
                    JobStatus.WAITING_FOR_QUOTA
                    if job.attempts <= 1
                    else JobStatus.WAITING_FOR_QUOTA
                )
                self.database.update_job_status(
                    job.id,
                    status,
                    error_code="quota_exhausted",
                    error_message=quota.message or "Provider quota is not currently available",
                    next_retry_at=reset,
                )
                return {"job_id": job.id, "status": status.value, "quota_id": quota.id}

        try:
            payload = handler(job) or {}
            self.database.update_job_status(job.id, JobStatus.SUCCESS)
            self.database.add_paper_extra(
                job.paper_id, {"last_job_result": payload}
            ) if job.paper_id else None
            return {"job_id": job.id, "status": JobStatus.SUCCESS.value, "payload": payload}
        except ProviderError as exc:
            status = classify_error(exc)
            if status == JobStatus.RETRY and job.attempts >= job.max_attempts:
                status = JobStatus.FAILED
            retry_at = None
            if status in {JobStatus.RETRY, JobStatus.WAITING_FOR_QUOTA}:
                retry_at = next_retry_at(
                    attempt=job.attempts,
                    base_delay_seconds=self.config.retry.base_delay_seconds,
                    max_delay_seconds=self.config.retry.max_delay_seconds,
                    retry_after=exc.retry_after,
                )
            self.database.update_job_status(
                job.id,
                status,
                error_code=exc.code,
                error_message=exc.message,
                next_retry_at=retry_at,
            )
            return {
                "job_id": job.id,
                "status": status.value,
                "error_code": exc.code,
                "error_message": exc.message,
            }
        except Exception as exc:  # noqa: BLE001 - scheduler must retain unexpected failures
            status = JobStatus.RETRY if job.attempts < job.max_attempts else JobStatus.FAILED
            self.database.update_job_status(
                job.id,
                status,
                error_code="internal_error",
                error_message=str(exc),
                next_retry_at=next_retry_at(
                    attempt=job.attempts,
                    base_delay_seconds=self.config.retry.base_delay_seconds,
                    max_delay_seconds=self.config.retry.max_delay_seconds,
                )
                if status == JobStatus.RETRY
                else None,
            )
            return {"job_id": job.id, "status": status.value, "error_message": str(exc)}

    def _quota_for(self, job: Job) -> QuotaState | None:
        if not job.provider or not job.service:
            return None
        return self.database.get_quota(job.provider, job.service, job.credential_id)

    def quota_runway(self, *, provider: str, service: str) -> dict[str, Any]:
        from sqlalchemy import func, select

        from lit_harvest.storage.database import JobRow

        with self.database.session() as session:
            queued = int(
                session.scalar(
                    select(func.count())
                    .select_from(JobRow)
                    .where(
                        JobRow.provider == provider,
                        JobRow.service == service,
                        JobRow.status.in_(
                            (
                                JobStatus.PENDING.value,
                                JobStatus.RETRY.value,
                                JobStatus.WAITING_FOR_QUOTA.value,
                            )
                        ),
                    )
                )
                or 0
            )
        quotas = [
            quota
            for quota in self.database.list_quotas()
            if quota.provider == provider and quota.service == service
        ]
        remaining_values = [quota.remaining for quota in quotas if quota.remaining is not None]
        remaining = sum(remaining_values) if remaining_values else None
        return {
            "provider": provider,
            "service": service,
            "queued_jobs": queued,
            "remaining": remaining,
            "sufficient": remaining is None or remaining >= queued,
            "shortfall": max(queued - remaining, 0) if remaining is not None else 0,
        }


def default_scheduler(database: Database, config: SchedulerConfig | None = None) -> Scheduler:
    return Scheduler(database, config=config, quotas=QuotaManager(database))


def shared_quota_scope(scope: str) -> QuotaScope:
    try:
        return QuotaScope(scope)
    except ValueError:
        return QuotaScope.UNKNOWN
