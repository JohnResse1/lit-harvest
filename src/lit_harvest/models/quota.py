"""Quota state models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from lit_harvest.models.enums import QuotaScope, QuotaSource, QuotaStatus


class QuotaState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    service: str
    credential_id: str | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    observed_at: datetime
    source: QuotaSource = QuotaSource.UNKNOWN
    quota_scope: QuotaScope = QuotaScope.UNKNOWN
    status: QuotaStatus = QuotaStatus.UNKNOWN
    message: str | None = None


class QuotaUpdate(BaseModel):
    provider: str
    service: str
    credential_id: str | None = None
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    source: QuotaSource = QuotaSource.UNKNOWN
    quota_scope: QuotaScope = QuotaScope.UNKNOWN
    status: QuotaStatus | None = None
    message: str | None = None
