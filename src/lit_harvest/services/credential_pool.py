"""Manage the multi-provider API key pool.

The pool is the single source of truth for "which credential should handle this
call". It deliberately keeps three concerns separate:

1. **Storage** - secrets live in `.lit-harvest/secrets.json`; only metadata and
   an environment/file reference are persisted in SQLite.
2. **Selection** - eligibility first (enabled, has a secret, not unhealthy, not
   cooling down), then health, then explicit priority, then least-recently-used.
3. **Compliance** - a quota shared by an institution never triggers rotation to
   a sibling credential, because that would circumvent the library's agreement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lit_harvest.credentials.manager import CredentialManager, CredentialUnavailableError
from lit_harvest.credentials.store import SecretStore, default_secret_ref, parse_secret_ref


class PoolError(RuntimeError):
    """Raised when a pool operation cannot be completed safely."""


@dataclass(slots=True)
class PoolEntry:
    credential_id: str
    provider: str
    name: str
    label: str
    secret_ref: str
    institution: str | None
    quota_scope: str
    enabled: bool
    health: str
    secret_available: bool
    priority: int
    last_used_at: str | None
    use_count: int
    notes: str | None

    def to_dict(self) -> dict[str, Any]:
        """Public representation. Never includes the secret itself."""
        return {
            "credential_id": self.credential_id,
            "provider": self.provider,
            "name": self.name,
            "label": self.label,
            "secret_ref": self.secret_ref,
            "institution": self.institution,
            "quota_scope": self.quota_scope,
            "enabled": self.enabled,
            "health": self.health,
            "secret_available": self.secret_available,
            "priority": self.priority,
            "last_used_at": self.last_used_at,
            "use_count": self.use_count,
            "notes": self.notes,
        }


class CredentialPoolService:
    """CRUD and diagnostics for provider credentials."""

    def __init__(self, credentials: CredentialManager, secrets: SecretStore):
        self.credentials = credentials
        self.secrets = secrets

    def entries(self, provider: str | None = None) -> list[PoolEntry]:
        providers = [provider] if provider else self.credentials.providers()
        entries: list[PoolEntry] = []
        for name in providers:
            entries.extend(self._entries_for(name))
        return entries

    def _entries_for(self, provider: str) -> list[PoolEntry]:
        rows = self.credentials.database.list_credentials(provider)
        entries: list[PoolEntry] = []
        for row in rows:
            entries.append(
                PoolEntry(
                    credential_id=row["id"],
                    provider=row["provider"],
                    name=row["name"],
                    label=row.get("account_label") or row["name"],
                    secret_ref=row["secret_ref"],
                    institution=row.get("institution"),
                    quota_scope=row.get("quota_scope") or "unknown",
                    enabled=bool(row.get("enabled")),
                    health=row.get("health_status") or "unknown",
                    secret_available=self.secrets.exists(row["secret_ref"]),
                    priority=int(row.get("priority") or 100),
                    last_used_at=(
                        row["last_used_at"].isoformat() if row.get("last_used_at") else None
                    ),
                    use_count=int(row.get("use_count") or 0),
                    notes=row.get("notes"),
                )
            )
        return entries

    # ------------------------------------------------------------------ write

    def add(
        self,
        *,
        provider: str,
        name: str,
        secret: str | None = None,
        secret_ref: str | None = None,
        institution: str | None = None,
        account_label: str | None = None,
        quota_scope: str = "unknown",
        priority: int = 100,
        notes: str | None = None,
        enabled: bool = True,
    ) -> PoolEntry:
        """Add or update a credential. The secret is never returned."""
        if not provider.strip() or not name.strip():
            raise PoolError("Provider and credential name are required.")
        ref = (secret_ref or "").strip() or default_secret_ref(provider, name)
        try:
            parse_secret_ref(ref)
        except ValueError as exc:
            raise PoolError(str(exc)) from exc

        if secret is not None and secret.strip():
            self.secrets.set(ref, secret.strip())
        elif not self.secrets.exists(ref):
            raise PoolError(
                "No secret was provided and none is stored for "
                f"{ref}. Paste the key, or store it first with `lit-harvest auth set`."
            )

        credential_id = self.credentials.database.upsert_credential(
            provider=provider,
            name=name,
            secret_ref=ref,
            account_label=account_label,
            institution=institution,
            quota_scope=quota_scope,
            enabled=enabled,
            notes=notes,
            priority=priority,
        )
        return next(
            item for item in self._entries_for(provider) if item.credential_id == credential_id
        )

    def set_enabled(self, credential_id: str, enabled: bool) -> PoolEntry:
        row = self.credentials.database.get_credential(credential_id)
        if row is None:
            raise PoolError(f"Credential not found: {credential_id}")
        self.credentials.database.set_credential_enabled(credential_id, enabled)
        provider = str(row["provider"])
        return next(
            item for item in self._entries_for(provider) if item.credential_id == credential_id
        )

    def remove(self, credential_id: str, *, delete_secret: bool = False) -> dict[str, Any]:
        row = self.credentials.database.get_credential(credential_id)
        if row is None:
            raise PoolError(f"Credential not found: {credential_id}")
        removed_secret = False
        if delete_secret:
            removed_secret = self.secrets.delete(str(row["secret_ref"]))
        self.credentials.database.delete_credential(credential_id)
        return {
            "credential_id": credential_id,
            "provider": row["provider"],
            "name": row["name"],
            "secret_deleted": removed_secret,
        }

    def healthcheck(self, provider: str) -> dict[str, Any]:
        """Check one provider's credentials without exposing secrets."""
        entries = self._entries_for(provider)
        return {
            "provider": provider,
            "credentials": [
                {
                    "name": item.name,
                    "secret_available": item.secret_available,
                    "enabled": item.enabled,
                    "health": item.health,
                    "eligible": item.enabled
                    and item.secret_available
                    and item.health != "unhealthy",
                }
                for item in entries
            ],
        }

    def selection_preview(self, provider: str, service: str) -> dict[str, Any]:
        """Explain which credential the pool would pick and why."""
        try:
            chosen = self.credentials.peek(provider, service)
        except CredentialUnavailableError as exc:
            return {
                "provider": provider,
                "service": service,
                "eligible": False,
                "message": str(exc),
            }
        return {
            "provider": provider,
            "service": service,
            "eligible": True,
            "selected": {
                "name": chosen.name,
                "health": chosen.health_status.value,
                "institution": chosen.institution,
                "quota_scope": chosen.quota_scope.value,
            },
            "reason": "highest health, then priority, then least recently used",
        }
