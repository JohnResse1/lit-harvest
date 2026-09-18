"""Queue and failure control operations used by CLI and API."""

from __future__ import annotations

from typing import Any

from lit_harvest.models import JobStatus
from lit_harvest.scheduler.scheduler import Scheduler
from lit_harvest.storage.database import Database


class MaintenanceService:
    TRANSIENT_CODES = {
        "rate_limit",
        "transient_provider_error",
        "timeout",
        "network_error",
        "internal_error",
    }

    def __init__(self, database: Database, scheduler: Scheduler):
        self.database = database
        self.scheduler = scheduler

    def pause(self, reason: str | None = None) -> None:
        self.scheduler.pause(reason)

    def resume(self) -> None:
        self.scheduler.resume()

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        self.database.update_job_status(job.id, JobStatus.PENDING)
        return {"job_id": job.id, "status": JobStatus.PENDING.value}

    def retry_transient(self) -> dict[str, int]:
        retried = 0
        for failure in self.database.list_failures(limit=1000):
            if failure.get("error_code") in self.TRANSIENT_CODES:
                self.database.update_job_status(str(failure["job_id"]), JobStatus.PENDING)
                retried += 1
        return {"retried": retried}

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        if job.status == JobStatus.RUNNING:
            raise ValueError("Running jobs must be cancelled by their worker")
        self.database.update_job_status(job.id, JobStatus.CANCELLED)
        return {"job_id": job.id, "status": JobStatus.CANCELLED.value}
