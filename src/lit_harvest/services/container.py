"""Composition root for configuration, persistence, providers, and services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lit_harvest.config import AppConfig, ProviderConfig, load_config
from lit_harvest.credentials.manager import CredentialManager
from lit_harvest.policy import PolicyService, ProviderPolicy
from lit_harvest.providers.elsevier import ElsevierProvider
from lit_harvest.providers.openalex import OpenAlexProvider
from lit_harvest.providers.registry import ProviderRegistry
from lit_harvest.quotas.manager import QuotaManager
from lit_harvest.scheduler.queue import QueueControl
from lit_harvest.scheduler.scheduler import Scheduler
from lit_harvest.scheduler.worker import Worker
from lit_harvest.services.acquisition import AcquisitionService
from lit_harvest.services.cache import CacheService
from lit_harvest.services.credential_pool import CredentialPoolService
from lit_harvest.services.dashboard import DashboardService
from lit_harvest.services.maintenance import MaintenanceService
from lit_harvest.services.normalization import NormalizationService
from lit_harvest.services.papers import PaperService
from lit_harvest.services.storage_settings import StorageSettingsService
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage


class DoctorResult(dict[str, Any]):
    """Typed mapping for diagnostics without leaking secrets."""


class ServiceContainer:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.database = Database(self.config.database.url)
        self.database.initialize()
        self.storage = DocumentStorage(self.config.storage.root)
        self.storage.ensure_layout()
        self.credentials = CredentialManager(self.config, self.database)
        self.quotas = QuotaManager(self.database)
        self.policy = self._build_policy_service()
        self.queue_control = QueueControl()
        self._sync_providers()
        self.providers: ProviderRegistry = self._build_providers()
        self.papers = PaperService(self.database)
        self.normalization = NormalizationService(self.database, self.storage)
        self.cache = CacheService(self.database, self.storage)
        self.acquisition = AcquisitionService(
            config=self.config,
            database=self.database,
            storage=self.storage,
            providers=self.providers,
            normalization=self.normalization,
            cache=self.cache,
        )
        self.scheduler = Scheduler(
            self.database,
            config=self.config.scheduler,
            quotas=self.quotas,
            queue_control=self.queue_control,
        )
        self.scheduler.register(self.acquisition.task_type, self.acquisition.handle_job)
        self.worker = Worker(
            self.scheduler,
            poll_interval_seconds=2.0,
        )
        self.dashboard = DashboardService(self.database, self.storage, self.scheduler)
        self.maintenance = MaintenanceService(self.database, self.scheduler)
        self.credential_pool = CredentialPoolService(self.credentials, self.credentials.secrets)
        self.storage_settings = StorageSettingsService(self.config, self.database)

    def _build_policy_service(self) -> PolicyService:
        """Translate configured policy settings into runtime pacing rules."""
        policies: dict[str, ProviderPolicy] = {}
        for name, provider_config in self.config.providers.all().items():
            configured = provider_config.policy
            unlimited = configured.unlimited
            policies[name] = ProviderPolicy(
                fulltext_min_interval_seconds=configured.fulltext_min_interval_seconds,
                pdf_min_interval_seconds=configured.pdf_min_interval_seconds,
                search_min_interval_seconds=configured.search_min_interval_seconds,
                fulltext_daily_limit=None if unlimited else configured.fulltext_daily_limit,
                pdf_daily_limit=None if unlimited else configured.pdf_daily_limit,
                search_daily_limit=None if unlimited else configured.search_daily_limit,
                jitter_ratio=configured.jitter_ratio,
            )
        return PolicyService(self.database, policies=policies)

    def _build_providers(self) -> ProviderRegistry:
        """Instantiate every enabled provider described by the configuration.

        New providers are added here as they are implemented; the rest of the
        application only talks to the registry and its capabilities.
        """
        registry = ProviderRegistry()
        # Each factory returns a Provider; the mapping stays typed so mypy can
        # verify that every registered provider satisfies the protocol.
        factories: dict[str, Callable[[ProviderConfig], Any]] = {
            "elsevier": self._build_elsevier,
            "openalex": self._build_openalex,
        }
        for name, provider_config in self.config.providers.all().items():
            if not provider_config.enabled:
                continue
            factory = factories.get(name)
            if factory is None:
                # Configured but not implemented in this build: ignore rather
                # than crash, so a shared config stays usable.
                continue
            registry.register(factory(provider_config))
        return registry

    def _build_elsevier(self, provider_config: ProviderConfig) -> ElsevierProvider:
        provider = ElsevierProvider(
            database=self.database,
            credentials=self.credentials,
            quotas=self.quotas,
            timeout_seconds=provider_config.timeout_seconds,
            max_attempts=self.config.scheduler.retry.max_attempts,
            policy=self.policy,
        )
        # Kept as an attribute for backwards compatibility with earlier code.
        self.elsevier = provider
        return provider

    def _build_openalex(self, provider_config: ProviderConfig) -> OpenAlexProvider:
        return OpenAlexProvider(
            database=self.database,
            contact_email=provider_config.contact_email,
            timeout_seconds=provider_config.timeout_seconds,
            max_attempts=self.config.scheduler.retry.max_attempts,
            policy=self.policy,
        )

    def _sync_providers(self) -> None:
        """Register provider/service rows and credential metadata in SQLite."""
        display_names = {"elsevier": "Elsevier", "openalex": "OpenAlex"}
        for name, provider_config in self.config.providers.all().items():
            services = [
                (service_name, service.enabled)
                for service_name, service in sorted(provider_config.services.items())
            ]
            self.database.sync_provider(
                name,
                display_names.get(name, name.title()),
                services,
                enabled=provider_config.enabled,
            )
        self.credentials.sync_configured_credentials()

    def doctor(self, *, network: bool = False) -> DoctorResult:
        db_ok, db_message = self.database.healthcheck()
        storage_ok, storage_message = self.storage.healthcheck()
        checks = DoctorResult(
            database={"ok": db_ok, "message": db_message},
            storage={"ok": storage_ok, "message": storage_message},
        )
        credentials = [
            item
            for name in self.config.providers.names()
            for item in self.credentials.list_credentials(name)
        ]
        checks["credentials"] = [
            {
                "name": item.name,
                "label": item.account_label or item.name,
                "institution": item.institution,
                "detected": item.secret_available,
                "health": item.health_status.value,
                "scope": item.quota_scope.value,
            }
            for item in credentials
        ]
        health = [
            result
            for provider in self.providers.all()
            for result in provider.healthcheck(network=network)
        ]
        checks["providers"] = [
            {
                "provider": item.provider,
                "service": item.service,
                "status": item.status.value,
                "message": item.message,
                "details": item.details,
            }
            for item in health
        ]
        if network:
            for item in health:
                self.database.set_provider_health(
                    item.provider,
                    item.status,
                    service=item.service,
                    message=item.message,
                )
        checks["quotas"] = [quota.model_dump(mode="json") for quota in self.database.list_quotas()]
        checks["ok"] = bool(db_ok and storage_ok) and any(
            item.secret_available for item in credentials
        )
        if not credentials:
            checks["credential_status"] = "not_configured"
        elif not any(item.secret_available for item in credentials):
            checks["credential_status"] = "secret_missing"
        else:
            checks["credential_status"] = "detected"
        checks["worker"] = {
            "running": self.worker.alive,
            "ticks": self.worker.state.ticks,
            "last_result": self.worker.state.last_result,
        }
        return checks
