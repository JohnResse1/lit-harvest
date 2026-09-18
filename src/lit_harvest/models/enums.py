"""Domain enumerations shared across persistence, CLI, API, and providers."""

from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    RETRY = "retry"
    WAITING_FOR_QUOTA = "waiting_for_quota"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    NOT_ENTITLED = "not_entitled"
    NOT_FOUND = "not_found"
    FAILED = "failed"


class TaskType(StrEnum):
    DISCOVER = "discover"
    RESOLVE = "resolve"
    FETCH_FULLTEXT = "fetch_fulltext"
    NORMALIZE = "normalize"
    PARSE = "parse"


class QuotaStatus(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    LOW = "low"
    COOLDOWN = "cooldown"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class QuotaScope(StrEnum):
    CREDENTIAL = "credential"
    ACCOUNT = "account"
    INSTITUTION = "institution"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


class QuotaSource(StrEnum):
    RESPONSE_HEADER = "response_header"
    LOCAL_ESTIMATE = "local_estimate"
    MANUAL_CONFIG = "manual_config"
    UNKNOWN = "unknown"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class AuthType(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    INSTITUTION_TOKEN = "institution_token"
    IP_ENTITLEMENT = "ip_entitlement"
    OTHER = "other"


class DownloadStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    NOT_ENTITLED = "not_entitled"
    NOT_FOUND = "not_found"


class PaperStage(StrEnum):
    DISCOVERED = "discovered"
    METADATA_RESOLVED = "metadata_resolved"
    FULLTEXT_RESOLVED = "fulltext_resolved"
    DOWNLOADED = "downloaded"
    NORMALIZED = "normalized"
    READY = "ready"
    FAILED = "failed"
