"""Rate pacing and daily ceilings that protect shared institutional access."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lit_harvest.api.app import create_app
from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ElsevierConfig,
    PolicyConfig,
    ProvidersConfig,
    StorageConfig,
)
from lit_harvest.policy import (
    DEFAULT_POLICY,
    PolicyLimitError,
    PolicyService,
    ProviderPolicy,
)
from lit_harvest.services.container import ServiceContainer
from lit_harvest.storage.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


def config_for(tmp_path: Path, policy: PolicyConfig | None = None) -> AppConfig:
    elsevier = ElsevierConfig()
    if policy is not None:
        elsevier = ElsevierConfig(policy=policy)
    return AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(entries={"elsevier": elsevier}),
    )


# ------------------------------------------------------------------- pacing


def test_first_call_is_not_delayed(database: Database) -> None:
    waits: list[float] = []
    service = PolicyService(database, sleep=waits.append, monotonic=lambda: 100.0)
    delay = service.wait_turn("elsevier", "article_retrieval")
    assert delay == 0.0
    assert waits == []


def test_second_call_waits_for_configured_interval(database: Database) -> None:
    waits: list[float] = []
    policy = ProviderPolicy(fulltext_min_interval_seconds=60.0, jitter_ratio=0.0)
    service = PolicyService(
        database, policies={"elsevier": policy}, sleep=waits.append, monotonic=lambda: 0.0
    )
    service.wait_turn("elsevier", "article_retrieval")
    service.wait_turn("elsevier", "article_retrieval")
    assert waits == [60.0]


def test_jitter_keeps_delay_within_bounds(database: Database) -> None:
    waits: list[float] = []
    policy = ProviderPolicy(fulltext_min_interval_seconds=60.0, jitter_ratio=0.25)
    service = PolicyService(
        database, policies={"elsevier": policy}, sleep=waits.append, monotonic=lambda: 0.0
    )
    service.wait_turn("elsevier", "article_retrieval")
    service.wait_turn("elsevier", "article_retrieval")
    assert waits, "second call should have waited"
    assert 45.0 <= waits[0] <= 75.0


def test_services_are_paced_independently(database: Database) -> None:
    waits: list[float] = []
    service = PolicyService(database, sleep=waits.append, monotonic=lambda: 0.0)
    service.wait_turn("elsevier", "article_retrieval")
    # A different service has its own clock, so no wait is triggered.
    service.wait_turn("elsevier", "article_pdf")
    assert waits == []


def test_pdf_pacing_is_more_conservative_than_fulltext() -> None:
    policy = DEFAULT_POLICY
    assert policy.pdf_min_interval_seconds > policy.fulltext_min_interval_seconds
    assert policy.search_min_interval_seconds < policy.fulltext_min_interval_seconds


# -------------------------------------------------------------- daily ceiling


def test_daily_limit_blocks_after_reaching_cap(database: Database) -> None:
    from lit_harvest.models import PaperCreate

    paper = database.create_paper(PaperCreate(doi="10.1000/a"))
    for _ in range(3):
        database.record_download(
            paper_id=paper.id,
            provider="elsevier",
            service="article_retrieval",
            credential_id=None,
            status="success",
            format="xml",
            raw_path=None,
            checksum=None,
        )
    policy = ProviderPolicy(fulltext_daily_limit=3)
    service = PolicyService(database, policies={"elsevier": policy})

    assert service.usage_today("elsevier", "article_retrieval") == 3
    with pytest.raises(PolicyLimitError) as excinfo:
        service.check_daily("elsevier", "article_retrieval")
    assert excinfo.value.limit == 3
    assert "protects the shared institutional subscription" in str(excinfo.value)


def test_usage_below_cap_is_allowed(database: Database) -> None:
    policy = ProviderPolicy(fulltext_daily_limit=10)
    service = PolicyService(database, policies={"elsevier": policy})
    service.check_daily("elsevier", "article_retrieval")  # no raise


def test_pdf_limit_is_counted_separately(database: Database) -> None:
    from lit_harvest.models import PaperCreate

    paper = database.create_paper(PaperCreate(doi="10.1000/a"))
    database.record_download(
        paper_id=paper.id,
        provider="elsevier",
        service="article_pdf",
        credential_id=None,
        status="success",
        format="pdf",
        raw_path=None,
        checksum=None,
    )
    service = PolicyService(database)
    assert service.usage_today("elsevier", "article_pdf") == 1
    assert service.usage_today("elsevier", "article_retrieval") == 0


def test_unlimited_disables_daily_ceiling(database: Database) -> None:
    policy = ProviderPolicy(
        fulltext_daily_limit=None, pdf_daily_limit=None, search_daily_limit=None
    )
    service = PolicyService(database, policies={"elsevier": policy})
    service.check_daily("elsevier", "article_retrieval")
    service.check_daily("elsevier", "article_pdf")


def test_unknown_provider_uses_default_policy(database: Database) -> None:
    service = PolicyService(database)
    assert service.policy_for("brand-new-publisher") is DEFAULT_POLICY


# ------------------------------------------------------------------ config


def test_policy_config_defaults_are_conservative() -> None:
    policy = PolicyConfig()
    assert policy.unlimited is False
    assert policy.fulltext_daily_limit == 100
    assert policy.pdf_daily_limit == 50
    assert policy.fulltext_min_interval_seconds >= 30


def test_configured_policy_reaches_runtime(tmp_path: Path) -> None:
    config = config_for(
        tmp_path,
        PolicyConfig(
            fulltext_daily_limit=7,
            fulltext_min_interval_seconds=0,
            jitter_ratio=0.0,
        ),
    )
    container = ServiceContainer(config)
    policy = container.policy.policy_for("elsevier")
    assert policy.fulltext_daily_limit == 7
    assert policy.fulltext_min_interval_seconds == 0


def test_unlimited_config_removes_runtime_caps(tmp_path: Path) -> None:
    config = config_for(
        tmp_path,
        PolicyConfig(unlimited=True, fulltext_daily_limit=100, pdf_daily_limit=50),
    )
    container = ServiceContainer(config)
    policy = container.policy.policy_for("elsevier")
    assert policy.fulltext_daily_limit is None
    assert policy.pdf_daily_limit is None
    assert policy.search_daily_limit is None


# ---------------------------------------------------------------- surfaces


def test_policy_endpoint_reports_limits_and_usage(tmp_path: Path) -> None:
    client = TestClient(create_app(config_for(tmp_path), start_worker=False))
    response = client.get("/api/policy")
    assert response.status_code == 200
    payload = response.json()
    elsevier = next(item for item in payload if item["provider"] == "elsevier")
    assert elsevier["fulltext_daily_limit"] == 100
    assert "usage" in elsevier
    assert elsevier["usage"]["article_retrieval"] == 0


def test_policy_cli_lists_caps() -> None:
    from typer.testing import CliRunner

    from lit_harvest.cli import app

    result = CliRunner().invoke(app, ["policy", "show"])
    assert result.exit_code == 0
    assert "Daily cap" in result.stdout
    assert "100" in result.stdout
