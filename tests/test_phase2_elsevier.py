from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from lit_harvest.config import (
    AppConfig,
    CredentialConfig,
    ElsevierConfig,
    ProvidersConfig,
    ServiceConfig,
)
from lit_harvest.credentials.manager import CredentialManager, CredentialUnavailableError
from lit_harvest.models import QuotaScope, QuotaSource, QuotaStatus, QuotaUpdate
from lit_harvest.providers.base import AuthenticationError
from lit_harvest.providers.elsevier.client import ElsevierClient
from lit_harvest.providers.elsevier.provider import ElsevierProvider
from lit_harvest.providers.elsevier.search import parse_search_response
from lit_harvest.quotas.manager import QuotaManager, parse_reset, parse_retry_after
from lit_harvest.storage.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


def config() -> AppConfig:
    return AppConfig(
        providers=ProvidersConfig(
            elsevier=ElsevierConfig(
                credentials=[
                    CredentialConfig(
                        name="primary",
                        api_key_env="ELSEVIER_KEY_PRIMARY",
                        institution="HIT",
                        quota_scope=QuotaScope.INSTITUTION.value,
                    ),
                    CredentialConfig(
                        name="secondary",
                        api_key_env="ELSEVIER_KEY_SECONDARY",
                        institution="HIT",
                        quota_scope=QuotaScope.INSTITUTION.value,
                    ),
                ],
                services={
                    "scopus_search": ServiceConfig(enabled=True),
                    "article_retrieval": ServiceConfig(enabled=True),
                },
            )
        )
    )


def test_search_standard_parser() -> None:
    payload = {
        "search-results": {
            "opensearch:totalResults": "2",
            "opensearch:startIndex": "0",
            "opensearch:itemsPerPage": "2",
            "cursor": {"@current": "*", "@next": "next"},
            "entry": [
                {
                    "dc:identifier": "SCOPUS_ID:85123456789",
                    "eid": "2-s2.0-85123456789",
                    "prism:doi": "10.1016/J.TEST.2026.1",
                    "dc:title": "Solid state batteries",
                    "dc:creator": "Zhang, L.",
                    "prism:publicationName": "Materials Today",
                    "prism:coverDate": "2026-01-01",
                    "citedby-count": "7",
                    "openaccess": "1",
                    "subtypeDescription": "Article",
                }
            ],
        }
    }
    papers, info = parse_search_response(payload)
    assert len(papers) == 1
    assert papers[0].doi == "10.1016/J.TEST.2026.1"
    assert papers[0].identifiers.scopus_id == "85123456789"
    assert papers[0].publication_year == 2026
    assert info["next_cursor"] == "next"


def test_search_pagination_and_raw_response(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    quotas = QuotaManager(database)
    pages = [
        httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "3",
                    "opensearch:startIndex": "0",
                    "opensearch:itemsPerPage": "2",
                    "cursor": {"@current": "*", "@next": "cursor-2"},
                    "entry": [
                        {"prism:doi": "10.1000/a", "dc:title": "A"},
                        {"prism:doi": "10.1000/b", "dc:title": "B"},
                    ],
                }
            },
            headers={
                "Content-Type": "application/json",
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "80",
            },
        ),
        httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "3",
                    "cursor": {"@current": "cursor-2", "@next": "cursor-3"},
                    "entry": [{"prism:doi": "10.1000/c", "dc:title": "C"}],
                }
            },
        ),
    ]
    client = ElsevierClient(transport=httpx.MockTransport(lambda request: pages.pop(0)))
    provider = ElsevierProvider(database=database, credentials=creds, quotas=quotas, client=client)
    result = provider.search("TITLE-ABS-KEY(test)", max_results=3)
    assert [paper.doi for page in result for paper in page.papers] == [
        "10.1000/a",
        "10.1000/b",
        "10.1000/c",
    ]
    assert result[0].raw.startswith(b'{"search-results"')
    quota = database.get_quota("elsevier", "scopus_search", result[0].credential.id)
    assert quota is not None
    assert quota.limit == 100
    assert quota.remaining == 78


def test_fulltext_retrieval_and_quota_headers(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    xml = b"<full-text-retrieval-response><doi>10.1016/x</doi></full-text-retrieval-response>"
    client = ElsevierClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=xml,
                headers={
                    "Content-Type": "text/xml",
                    "X-RateLimit-Limit": "1000",
                    "X-RateLimit-Remaining": "900",
                },
            )
        )
    )
    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=client,
    )
    result = provider.fetch_fulltext("10.1016/x")
    assert result.content == xml
    assert result.format == "xml"
    assert result.http_status == 200
    assert result.credential is not None
    quota = database.get_quota("elsevier", "article_retrieval", result.credential.id)
    assert quota is not None
    assert quota.remaining == 899


def test_auth_error_is_not_retried(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "bad")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "invalid key"})

    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(transport=httpx.MockTransport(handler), sleep=lambda _: None),
    )
    with pytest.raises(AuthenticationError):
        provider.fetch_fulltext("10.1016/x")
    assert calls == 1


def test_rate_limit_retry_after_is_honored(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, text="slow down")
        return httpx.Response(200, content=b"<xml/>", headers={"Content-Type": "text/xml"})

    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(
            transport=httpx.MockTransport(handler), sleep=sleeps.append, max_attempts=2
        ),
    )
    assert provider.fetch_fulltext("10.1016/x").http_status == 200
    assert sleeps == [3.0]


def test_quota_header_parsing() -> None:
    assert parse_reset("1700000000") == datetime.fromtimestamp(1700000000, tz=UTC)
    assert parse_reset("Wed, 21 Oct 2015 07:28:00 GMT") == datetime(2015, 10, 21, 7, 28, tzinfo=UTC)
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("0") == 0.0
    assert parse_retry_after("nonsense") is None


def test_credential_selection_blocks_same_institution_failover(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret-1")
    monkeypatch.setenv("ELSEVIER_KEY_SECONDARY", "secret-2")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    primary, _secondary = creds.list_credentials("elsevier")
    database.upsert_quota(
        QuotaUpdate(
            provider="elsevier",
            service="article_retrieval",
            credential_id=primary.id,
            remaining=0,
            reset_at=datetime(2099, 1, 1, tzinfo=UTC),
            source=QuotaSource.RESPONSE_HEADER,
            quota_scope=QuotaScope.INSTITUTION,
            status=QuotaStatus.COOLDOWN,
        )
    )
    with pytest.raises(CredentialUnavailableError):
        creds.select("elsevier", "article_retrieval", previous_credential_id=primary.id)


def test_403_degrades_service_but_keeps_credential_healthy(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    database.sync_provider(
        "elsevier",
        "Elsevier",
        [("scopus_search", True), ("article_retrieval", True)],
    )
    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, json={"error": "not entitled"})
            ),
            sleep=lambda _: None,
        ),
    )
    from lit_harvest.providers.base import EntitlementError

    with pytest.raises(EntitlementError):
        provider.fetch_fulltext("10.1016/x")
    credential = creds.list_credentials("elsevier")[0]
    assert credential.health_status.value == "unknown"
    service = next(
        item
        for item in database.list_providers()[0]["services"]
        if item["name"] == "article_retrieval"
    )
    assert service["health_status"] == "degraded"


def test_healthcheck_does_not_crash_without_eligible_credential(database: Database) -> None:
    provider = ElsevierProvider(
        database=database,
        credentials=CredentialManager(config(), database),
        quotas=QuotaManager(database),
        client=ElsevierClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))),
    )
    results = provider.healthcheck(network=True)
    assert len(results) == 2
    assert all(item.status.value == "unknown" for item in results)
