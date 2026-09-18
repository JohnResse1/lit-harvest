"""Job queue domain models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lit_harvest.models.enums import JobStatus, TaskType


class JobCreate(BaseModel):
    task_type: TaskType
    paper_id: str | None = None
    provider: str | None = None
    service: str | None = None
    credential_id: str | None = None
    priority: int = 100
    max_attempts: int = 4
    payload: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    paper_id: str | None = None
    task_type: TaskType
    provider: str | None = None
    service: str | None = None
    credential_id: str | None = None
    priority: int = 100
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    max_attempts: int = 4
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    next_retry_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
