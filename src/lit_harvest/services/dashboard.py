"""Dashboard summaries computed from backend state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from lit_harvest.models import JobStatus, PaperStage
from lit_harvest.scheduler.scheduler import Scheduler
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage


class DashboardService:
    def __init__(self, database: Database, storage: DocumentStorage, scheduler: Scheduler):
        self.database = database
        self.storage = storage
        self.scheduler = scheduler

    def overview(self) -> dict[str, Any]:
        paper_counts = {
            "discovered": self.database.count_papers(PaperStage.DISCOVERED),
            "metadata_resolved": self.database.count_papers(PaperStage.METADATA_RESOLVED),
            "fulltext_resolved": self.database.count_papers(PaperStage.FULLTEXT_RESOLVED),
            "downloaded": self.database.count_papers(PaperStage.DOWNLOADED),
            "normalized": self.database.count_papers(PaperStage.NORMALIZED),
            "ready": self.database.count_papers(PaperStage.READY),
        }
        job_counts = self.database.job_counts()
        failures = self.database.list_failures(limit=20)
        recent_papers = [
            paper.model_dump(mode="json") for paper in self.database.list_papers(limit=8)
        ]
        quotas = [quota.model_dump(mode="json") for quota in self.database.list_quotas()]
        return {
            "papers": {
                "total": self.database.count_papers(),
                "unique_doi": self.database.count_papers(),
                "fulltext_retrieved": paper_counts["downloaded"]
                + paper_counts["normalized"]
                + paper_counts["ready"],
                "normalized": paper_counts["normalized"] + paper_counts["ready"],
                "stages": paper_counts,
            },
            "jobs": {
                "total": sum(job_counts.values()),
                "by_status": job_counts,
                "queued": job_counts.get(JobStatus.PENDING.value, 0)
                + job_counts.get(JobStatus.RETRY.value, 0)
                + job_counts.get(JobStatus.WAITING_FOR_QUOTA.value, 0),
                "running": job_counts.get(JobStatus.RUNNING.value, 0),
                "failed": sum(
                    job_counts.get(status.value, 0)
                    for status in (
                        JobStatus.FAILED,
                        JobStatus.NOT_ENTITLED,
                        JobStatus.NOT_FOUND,
                        JobStatus.BLOCKED,
                    )
                ),
            },
            "pipeline": [
                {"stage": "Discovery", "count": paper_counts["discovered"]},
                {
                    "stage": "Metadata",
                    "count": paper_counts["metadata_resolved"]
                    + paper_counts["fulltext_resolved"]
                    + paper_counts["downloaded"]
                    + paper_counts["normalized"]
                    + paper_counts["ready"],
                },
                {
                    "stage": "Full-text resolution",
                    "count": paper_counts["fulltext_resolved"]
                    + paper_counts["downloaded"]
                    + paper_counts["normalized"]
                    + paper_counts["ready"],
                },
                {
                    "stage": "Download",
                    "count": paper_counts["downloaded"]
                    + paper_counts["normalized"]
                    + paper_counts["ready"],
                },
                {
                    "stage": "Normalization",
                    "count": paper_counts["normalized"] + paper_counts["ready"],
                },
            ],
            "quota": {
                "states": quotas,
                "runways": [
                    self.scheduler.quota_runway(provider="elsevier", service="article_retrieval"),
                    self.scheduler.quota_runway(provider="elsevier", service="scopus_search"),
                ],
            },
            "failures": failures,
            "recent_papers": recent_papers,
            "queue": {"paused": self.scheduler.queue.paused, "reason": self.scheduler.queue.reason},
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def providers(self) -> list[dict[str, Any]]:
        providers = self.database.list_providers()
        credentials = self.database.list_credentials()
        quotas = self.database.list_quotas()
        for provider in providers:
            provider["credentials"] = [
                {
                    "id": credential["id"],
                    "name": credential["name"],
                    "label": credential["account_label"] or credential["name"],
                    "institution": credential["institution"],
                    "quota_scope": credential["quota_scope"],
                    "health": credential["health_status"],
                    "enabled": credential["enabled"],
                }
                for credential in credentials
                if credential["provider"] == provider["name"]
            ]
            for service in provider["services"]:
                service["quotas"] = [
                    quota
                    for quota in quotas
                    if quota.provider == provider["name"] and quota.service == service["name"]
                ]
        return providers
