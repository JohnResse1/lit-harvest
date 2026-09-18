"""Credential selection and secret resolution without quota-evasion behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lit_harvest.config import AppConfig
from lit_harvest.credentials.store import SecretStore
from lit_harvest.models import Credential, HealthStatus, QuotaScope, QuotaStatus
from lit_harvest.storage.database import Database


class CredentialUnavailableError(RuntimeError):
    pass


class CredentialManager:
    """Resolves credential metadata and applies conservative failover rules."""

    def __init__(self, config: AppConfig, database: Database, secrets: SecretStore | None = None):
        self.config = config
        self.database = database
        project_root = config.config_path.parent if config.config_path else Path.cwd()
        self.secrets = secrets or SecretStore(project_root=project_root)

    def sync_configured_credentials(self) -> list[str]:
        """Upsert credential metadata for every configured provider."""
        ids: list[str] = []
        valid_scopes = {value.value for value in QuotaScope}
        for provider_name, provider in self.config.providers.all().items():
            if not provider.enabled:
                continue
            for item in provider.credentials:
                scope = (
                    item.quota_scope
                    if item.quota_scope in valid_scopes
                    else QuotaScope.UNKNOWN.value
                )
                credential_id = self.database.upsert_credential(
                    provider=provider_name,
                    name=item.name,
                    secret_ref=item.secret_ref_for(provider_name),
                    account_label=item.account_label,
                    institution=item.institution,
                    quota_scope=scope,
                    enabled=item.enabled,
                )
                ids.append(credential_id)
        return ids

    def providers(self) -> list[str]:
        return self.config.providers.names()

    def list_credentials(
        self, provider: str, *, include_secret_availability: bool = True
    ) -> list[Credential]:
        credentials: list[Credential] = []
        for item in self.database.list_credentials(provider):
            credential = Credential(
                id=item["id"],
                provider=item["provider"],
                name=item["name"],
                auth_type=item["auth_type"],
                secret_ref=item["secret_ref"],
                account_label=item["account_label"],
                institution=item["institution"],
                quota_scope=item["quota_scope"],
                enabled=item["enabled"],
                health_status=item["health_status"],
                last_checked_at=item["last_checked_at"],
                secret_available=self.secrets.exists(item["secret_ref"]),
            )
            if include_secret_availability or credential.enabled:
                credentials.append(credential)
        return credentials

    def resolve_secret(self, credential_id: str) -> str | None:
        item = self.database.get_credential(credential_id)
        if item is None:
            raise KeyError(f"Credential not found: {credential_id}")
        return self.secrets.get(item["secret_ref"])

    def select(
        self,
        provider: str,
        service: str,
        *,
        excluded_ids: set[str] | None = None,
        previous_credential_id: str | None = None,
    ) -> Credential:
        excluded = set(excluded_ids or set())
        if previous_credential_id:
            excluded.add(previous_credential_id)
            self._add_shared_quota_peers(provider, service, previous_credential_id, excluded)

        candidates: list[Credential] = []
        for credential in self.list_credentials(provider):
            if (
                credential.id in excluded
                or not credential.enabled
                or not credential.secret_available
            ):
                continue
            if credential.health_status == HealthStatus.UNHEALTHY:
                continue
            if self._is_blocked(provider, service, credential):
                continue
            candidates.append(credential)

        if not candidates:
            raise CredentialUnavailableError(
                f"No eligible credential for {provider}/{service}. "
                "Run `lit-harvest auth set` or check credential health and quota."
            )
        rank = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.UNKNOWN: 1,
            HealthStatus.DEGRADED: 2,
        }
        candidates.sort(key=lambda item: (rank.get(item.health_status, 3), item.name))
        return candidates[0]

    def _is_blocked(self, provider: str, service: str, credential: Credential) -> bool:
        quota = self.database.get_quota(provider, service, credential.id)
        if quota is None or quota.status not in {QuotaStatus.COOLDOWN, QuotaStatus.EXHAUSTED}:
            return False
        if quota.reset_at is None:
            return True
        return quota.reset_at > datetime.now(UTC)

    def _add_shared_quota_peers(
        self, provider: str, service: str, previous_credential_id: str, excluded: set[str]
    ) -> None:
        previous = self.database.get_credential(previous_credential_id)
        if previous is None:
            return
        quota = self.database.get_quota(provider, service, previous_credential_id)
        if quota is None:
            return
        # Only fail over across credentials with independently scoped authorization.
        if quota.quota_scope == QuotaScope.CREDENTIAL:
            return
        for item in self.database.list_credentials(provider):
            if item["id"] == previous_credential_id:
                continue
            same_scope = (
                quota.quota_scope == QuotaScope.INSTITUTION
                and item["institution"] == previous["institution"]
            ) or (
                quota.quota_scope == QuotaScope.ACCOUNT
                and item["account_label"] == previous["account_label"]
            )
            if same_scope or quota.quota_scope in {
                QuotaScope.PROVIDER,
                QuotaScope.UNKNOWN,
            }:
                excluded.add(item["id"])
