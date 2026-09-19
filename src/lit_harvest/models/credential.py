"""Credential metadata models. Secrets are never persisted here."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from lit_harvest.models.enums import AuthType, HealthStatus, QuotaScope


class Credential(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    name: str
    auth_type: AuthType = AuthType.API_KEY
    secret_ref: str
    account_label: str | None = None
    institution: str | None = None
    quota_scope: QuotaScope = QuotaScope.UNKNOWN
    enabled: bool = True
    health_status: HealthStatus = HealthStatus.UNKNOWN
    last_checked_at: datetime | None = None
    secret_available: bool = False
    priority: int = 100
    last_used_at: datetime | None = None
    use_count: int = 0
