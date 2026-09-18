"""Provider registry models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from lit_harvest.models.enums import HealthStatus


class ProviderService(BaseModel):
    name: str
    enabled: bool = True
    health_status: HealthStatus = HealthStatus.UNKNOWN
    last_checked_at: datetime | None = None
    message: str | None = None


class Provider(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    display_name: str
    enabled: bool = True
    health_status: HealthStatus = HealthStatus.UNKNOWN
    last_checked_at: datetime | None = None
    services: list[ProviderService] = Field(default_factory=list)
