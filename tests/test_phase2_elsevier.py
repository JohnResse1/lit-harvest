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
from lit_harvest.providers.base import AuthenticationError, ProviderError
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
    """Pagination walks `start` in 25-item pages and still preserves raw JSON."""
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    quotas = QuotaManager(database)
    seen_starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        start_index = int(params.get("start", "0"))
        seen_starts.append(start_index)
        if start_index == 0:
            entries = [
                {"prism:doi": f"10.1000/a{index}", "dc:title": f"A{index}"} for index in range(25)
            ]
        else:
            entries = [
                {"prism:doi": f"10.1000/b{index}", "dc:title": f"B{index}"} for index in range(5)
            ]
        return httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "30",
                    "opensearch:startIndex": str(start_index),
                    "opensearch:itemsPerPage": "25",
                    "entry": entries,
                }
            },
            headers={
                "Content-Type": "application/json",
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "80",
            },
        )

    client = ElsevierClient(transport=httpx.MockTransport(handler))
    provider = ElsevierProvider(database=database, credentials=creds, quotas=quotas, client=client)
    result = provider.search("TITLE-ABS-KEY(test)", max_results=30)

    assert seen_starts == [0, 25], f"unexpected pagination: {seen_starts}"
    dois = [paper.doi for page in result for paper in page.papers]
    assert len(dois) == 30
    assert dois[0] == "10.1000/a0"
    assert dois[-1] == "10.1000/b4"
    assert result[0].raw.startswith(b'{"search-results"')
    assert result[0].total_results == 30

    quota = database.get_quota("elsevier", "scopus_search", result[0].credential.id)
    assert quota is not None
    assert quota.limit == 100
    # The header reports 80 remaining; the local estimate consumes one more unit.
    assert quota.remaining == 79


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


def test_fetch_pdf_returns_binary_and_tracks_quota(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    payload = b"%PDF-1.7\nfake pdf body\n%%EOF"
    client = ElsevierClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=payload,
                headers={
                    "Content-Type": "application/pdf",
                    "X-RateLimit-Limit": "500",
                    "X-RateLimit-Remaining": "499",
                },
            )
        )
    )
    provider = ElsevierProvider(
        database=database, credentials=creds, quotas=QuotaManager(database), client=client
    )
    result = provider.fetch_pdf("10.1016/x")
    assert result.format == "pdf"
    assert result.content.startswith(b"%PDF")
    assert result.credential is not None
    quota = database.get_quota("elsevier", "article_pdf", result.credential.id)
    assert quota is not None
    assert quota.remaining == 498


def test_fetch_pdf_rejects_non_pdf_response(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=b"<xml/>", headers={"Content-Type": "text/xml"}
                )
            ),
            sleep=lambda _: None,
        ),
    )
    with pytest.raises(ProviderError, match="did not return a PDF"):
        provider.fetch_pdf("10.1016/x")


def test_first_search_page_omits_cursor_parameter(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Elsevier restricts the cursor parameter; page one must not send it."""
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    seen_params: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "1",
                    "opensearch:itemsPerPage": "1",
                    "entry": [{"prism:doi": "10.1000/cursor-test", "dc:title": "T"}],
                }
            },
            headers={"Content-Type": "application/json"},
        )

    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(transport=httpx.MockTransport(handler)),
    )
    provider.search("TITLE-ABS-KEY(x)", max_results=1)
    assert seen_params, "no request was made"
    assert "cursor" not in seen_params[0], "first page must omit the restricted cursor parameter"
    assert "cursor" not in seen_params[0], "cursor=* is equivalent and also restricted"


def test_search_never_requests_more_than_25_per_page(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scopus returns HTTP 400 for count > 25, so pages must stay small."""
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    requested_counts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        requested_counts.append(int(params.get("count", "0")))
        start = int(params.get("start", "0"))
        # Return a full page so pagination continues.
        entries = [
            {"prism:doi": f"10.1000/page-{start}-{index}", "dc:title": "T"} for index in range(25)
        ]
        return httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "1000",
                    "opensearch:itemsPerPage": "25",
                    "entry": entries,
                }
            },
            headers={"Content-Type": "application/json"},
        )

    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(transport=httpx.MockTransport(handler)),
    )
    pages = provider.search("TITLE-ABS-KEY(x)", max_results=100)

    assert requested_counts, "no requests were made"
    assert max(requested_counts) <= 25, f"count exceeded the Scopus cap: {requested_counts}"
    assert sum(len(page.papers) for page in pages) == 100


def test_search_uses_start_pagination_not_cursor(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restricted cursor parameter must not be used for paging."""
    monkeypatch.setenv("ELSEVIER_KEY_PRIMARY", "secret")
    creds = CredentialManager(config(), database)
    creds.sync_configured_credentials()
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        start = int(params.get("start", "0"))
        entries = [{"prism:doi": f"10.1000/p{start}-{i}", "dc:title": "T"} for i in range(25)]
        return httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "500",
                    "entry": entries,
                }
            },
            headers={"Content-Type": "application/json"},
        )

    provider = ElsevierProvider(
        database=database,
        credentials=creds,
        quotas=QuotaManager(database),
        client=ElsevierClient(transport=httpx.MockTransport(handler)),
    )
    provider.search("TITLE-ABS-KEY(x)", max_results=50)

    assert all("cursor" not in params for params in seen)
    starts = [int(params.get("start", "0")) for params in seen]
    assert starts == [0, 25]
