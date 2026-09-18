"""Composition root for configuration, persistence, providers, and services."""

from __future__ import annotations

from typing import Any

from lit_harvest.config import AppConfig, load_config
from lit_harvest.credentials.manager import CredentialManager
from lit_harvest.providers.elsevier import ElsevierProvider
from lit_harvest.providers.registry import ProviderRegistry, build_default_registry
from lit_harvest.quotas.manager import QuotaManager
from lit_harvest.scheduler.queue import QueueControl
from lit_harvest.scheduler.scheduler import Scheduler
from lit_harvest.scheduler.worker import Worker
from lit_harvest.services.acquisition import AcquisitionService
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
        self.queue_control = QueueControl()
        self._sync_providers()
        elsevier_config = self.config.providers.elsevier
        self.elsevier = ElsevierProvider(
            database=self.database,
            credentials=self.credentials,
            quotas=self.quotas,
            timeout_seconds=elsevier_config.timeout_seconds,
            max_attempts=self.config.scheduler.retry.max_attempts,
        )
        self.providers: ProviderRegistry = build_default_registry(self.elsevier)
        self.papers = PaperService(self.database)
        self.normalization = NormalizationService(self.database, self.storage)
        self.acquisition = AcquisitionService(
            config=self.config,
            database=self.database,
            storage=self.storage,
            providers=self.providers,
            normalization=self.normalization,
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
        self.storage_settings = StorageSettingsService(self.config, self.database)

    def _sync_providers(self) -> None:
        elsevier = self.config.providers.elsevier
        services = [(name, service.enabled) for name, service in sorted(elsevier.services.items())]
        self.database.sync_provider(
            "elsevier",
            "Elsevier",
            services,
            enabled=elsevier.enabled,
        )
        self.credentials.sync_configured_credentials()

    def doctor(self, *, network: bool = False) -> DoctorResult:
        db_ok, db_message = self.database.healthcheck()
        storage_ok, storage_message = self.storage.healthcheck()
        checks = DoctorResult(
            database={"ok": db_ok, "message": db_message},
            storage={"ok": storage_ok, "message": storage_message},
        )
        credentials = self.credentials.list_credentials("elsevier")
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
        health = self.elsevier.healthcheck(network=network)
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
