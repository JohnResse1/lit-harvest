"""Key-free providers: Crossref TDM links, Unpaywall, Europe PMC full text."""

from pathlib import Path

import httpx
import pytest

from lit_harvest.config import (
    AppConfig,
    CrossrefConfig,
    DatabaseConfig,
    EuropePmcConfig,
    ProvidersConfig,
    StorageConfig,
    UnpaywallConfig,
)
from lit_harvest.providers.crossref.parser import (
    extract_tdm_links,
    parse_crossref_record,
    parse_search_response,
)
from lit_harvest.providers.crossref.provider import CrossrefProvider
from lit_harvest.providers.europepmc.parser import (
    parse_europepmc_record,
)
from lit_harvest.providers.europepmc.parser import (
    parse_search_response as parse_epmc_search,
)
from lit_harvest.providers.europepmc.provider import EuropePmcProvider
from lit_harvest.providers.http import JsonHttpClient
from lit_harvest.providers.registry import ProviderRegistry
from lit_harvest.providers.unpaywall.parser import (
    parse_oa_locations,
    parse_unpaywall_record,
)
from lit_harvest.providers.unpaywall.provider import UnpaywallProvider
from lit_harvest.services.container import ServiceContainer
from lit_harvest.services.resolver import Resolver
from lit_harvest.storage.database import Database

FIXTURES = Path(__file__).parent / "fixtures"

# A trimmed Crossref work record, shaped like the real API response.
CROSSREF_WORK = {
    "DOI": "10.1016/j.mtcomm.2026.115551",
    "title": ["Solid-state battery interfaces"],
    "container-title": ["Materials Today Communications"],
    "short-container-title": ["Mater. Today Commun."],
    "publisher": "Elsevier BV",
    "type": "journal-article",
    "issued": {"date-parts": [[2026, 6, 1]]},
    "author": [
        {"given": "Wei", "family": "Li", "ORCID": "https://orcid.org/0000-0002-1234-5678"},
        {"given": "Ana", "family": "Garcia"},
    ],
    "ISSN": ["2352-4928"],
    "volume": "42",
    "page": "115551",
    "subject": ["Materials Chemistry"],
    "is-referenced-by-count": 3,
    # This is the important part: publisher-registered TDM routes.
    "link": [
        {
            "URL": "https://api.elsevier.com/content/article/PII:S1?httpAccept=text/xml",
            "content-type": "text/xml",
            "content-version": "vor",
            "intended-application": "text-mining",
        },
        {"URL": "https://example.org/landing", "intended-application": "unspecified"},
    ],
    "license": [
        {"URL": "https://www.elsevier.com/tdm/userlicense/1.0/", "content-version": "tdm"}
    ],
}

UNPAYWALL_RECORD = {
    "doi": "10.1234/green.2026.1",
    "is_oa": True,
    "oa_status": "green",
    "journal_is_oa": False,
    "publisher": "Test Publisher",
    "title": "A green open access paper",
    "year": 2026,
    "oa_locations": [
        {
            "url_for_landing_page": "https://repo.example.org/item/1",
            "host_type": "repository",
            "version": "acceptedVersion",
            "license": "cc-by-nc",
            "is_best": True,
        },
        {
            "url_for_pdf": "https://repo.example.org/item/1.pdf",
            "url_for_landing_page": "https://repo.example.org/item/1",
            "host_type": "repository",
            "version": "acceptedVersion",
            "license": "cc-by-nc",
            "is_best": True,
        },
    ],
}

EPMC_RECORD = {
    "id": "12345678",
    "source": "MED",
    "pmid": "12345678",
    "pmcid": "PMC9999999",
    "doi": "10.1234/epmc.2026.1",
    "title": "Open access full text in Europe PMC",
    "authorList": {
        "author": [
            {"fullName": "Ada Lovelace", "authorId": "0000-0001-2", "authorIdType": "ORCID"},
            {"firstName": "Grace", "lastName": "Hopper"},
        ]
    },
    "authorCount": 2,
    "journalInfo": {
        "volume": "10",
        "issue": "2",
        "journal": {"title": "Journal of Open Tests"},
    },
    "pubYear": "2026",
    "isOpenAccess": "Y",
    "pageInfo": "1-10",
    "abstractText": "Europe PMC hosts structured full text.",
}


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'state.db'}")
    db.initialize()
    return db


# ------------------------------------------------------------ Crossref parse


def test_crossref_extracts_only_text_mining_links() -> None:
    links = extract_tdm_links(CROSSREF_WORK)
    assert len(links) == 1
    assert links[0]["url"].startswith("https://api.elsevier.com")
    assert links[0]["content_type"] == "text/xml"
    # An ordinary landing link must never be treated as a TDM route.
    assert all("landing" not in link["url"] for link in links)


def test_crossref_record_maps_metadata() -> None:
    paper = parse_crossref_record(CROSSREF_WORK)
    assert paper.doi == "10.1016/j.mtcomm.2026.115551"
    assert paper.title == "Solid-state battery interfaces"
    assert paper.journal == "Materials Today Communications"
    assert paper.publication_year == 2026
    assert paper.publisher == "Elsevier BV"
    assert paper.extra["author_count"] == 2
    assert paper.extra["tdm_links"][0]["content_version"] == "vor"
    assert paper.extra["is_referenced_by_count"] == 3


def test_crossref_search_response_reads_totals() -> None:
    papers, info = parse_search_response(
        {"message": {"items": [CROSSREF_WORK], "total-results": 42, "items-per-page": 1}}
    )
    assert len(papers) == 1
    assert info["total_results"] == 42


def test_crossref_tolerates_missing_link_field() -> None:
    record = dict(CROSSREF_WORK)
    del record["link"]
    assert extract_tdm_links(record) == []


def test_crossref_provider_is_key_free(database: Database) -> None:
    provider = CrossrefProvider(database=database)
    assert provider.requires_credential is False
    assert provider.supports_tdm_links is True


def test_crossref_fetch_tdm_links_returns_routes(database: Database) -> None:
    client = JsonHttpClient(
        base_url="https://api.crossref.org",
        provider="crossref",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"message": CROSSREF_WORK})
        ),
        sleep=lambda _: None,
    )
    provider = CrossrefProvider(database=database, client=client)
    links = provider.fetch_tdm_links("10.1016/j.mtcomm.2026.115551")
    assert links and links[0]["url"].startswith("https://api.elsevier.com")


def test_crossref_search_sends_polite_pool_email(database: Database) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("mailto", ""))
        return httpx.Response(
            200, json={"message": {"items": [CROSSREF_WORK], "total-results": 1}}
        )

    client = JsonHttpClient(
        base_url="https://api.crossref.org",
        provider="crossref",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    provider = CrossrefProvider(database=database, client=client, contact_email="a@b.org")
    provider.search("battery", max_results=1)
    assert seen[0] == "a@b.org"


# ----------------------------------------------------------- Unpaywall parse


def test_unpaywall_prefers_direct_pdf_location() -> None:
    record = parse_unpaywall_record(UNPAYWALL_RECORD)
    assert record["is_oa"] is True
    assert record["downloadable"] is True
    assert record["pdf_url"] == "https://repo.example.org/item/1.pdf"
    assert record["oa_status"] == "green"


def test_unpaywall_landing_only_is_not_downloadable() -> None:
    raw = dict(UNPAYWALL_RECORD)
    raw["oa_locations"] = [UNPAYWALL_RECORD["oa_locations"][0]]
    record = parse_unpaywall_record(raw)
    assert record["is_oa"] is True
    assert record["downloadable"] is False
    assert record["pdf_url"] is None


def test_unpaywall_location_order_sorts_pdf_first() -> None:
    locations = parse_oa_locations(UNPAYWALL_RECORD)
    assert locations[0]["url_for_pdf"] is not None


def test_unpaywall_requires_contact_email(database: Database) -> None:
    provider = UnpaywallProvider(database=database)
    assert provider.configured is False
    # Without an email it stays inert rather than making anonymous calls.
    assert provider.fetch_oa_location("10.1234/x") is None


def test_unpaywall_lookup_returns_location_when_configured(database: Database) -> None:
    client = JsonHttpClient(
        base_url="https://api.unpaywall.org",
        provider="unpaywall",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=UNPAYWALL_RECORD)
        ),
        sleep=lambda _: None,
    )
    provider = UnpaywallProvider(database=database, client=client, contact_email="a@b.org")
    result = provider.fetch_oa_location("10.1234/green.2026.1")
    assert result is not None and result["pdf_url"].endswith(".pdf")


def test_unpaywall_closed_access_returns_none(database: Database) -> None:
    client = JsonHttpClient(
        base_url="https://api.unpaywall.org",
        provider="unpaywall",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"is_oa": False})
        ),
        sleep=lambda _: None,
    )
    provider = UnpaywallProvider(database=database, client=client, contact_email="a@b.org")
    assert provider.fetch_oa_location("10.1234/closed") is None


# ----------------------------------------------------------- Europe PMC parse


def test_europepmc_record_maps_metadata_and_pmcid() -> None:
    paper = parse_europepmc_record(EPMC_RECORD)
    assert paper.doi == "10.1234/epmc.2026.1"
    assert paper.title == "Open access full text in Europe PMC"
    assert paper.journal == "Journal of Open Tests"
    assert paper.publication_year == 2026
    assert paper.identifiers.pmcid == "PMC9999999"
    assert paper.identifiers.pmid == "12345678"
    assert paper.extra["author_count"] == 2
    assert paper.extra["is_oa"] is True


def test_europepmc_search_response_reads_cursor() -> None:
    papers, info = parse_epmc_search(
        {
            "hitCount": 100,
            "nextCursorMark": "AoJ123",
            "resultList": {"result": [EPMC_RECORD]},
        }
    )
    assert len(papers) == 1
    assert info["total_results"] == 100
    assert info["next_cursor"] == "AoJ123"


def test_europepmc_oa_lookup_returns_jats_url(database: Database) -> None:
    client = JsonHttpClient(
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
        provider="europepmc",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"resultList": {"result": [EPMC_RECORD]}})
        ),
        sleep=lambda _: None,
    )
    provider = EuropePmcProvider(database=database, client=client)
    result = provider.fetch_oa_location("10.1234/epmc.2026.1")
    assert result is not None
    # Structured JATS, not a PDF: the resolver must not mislabel it.
    assert result["file_format"] == "xml"
    assert result["pdf_url"].endswith("/PMC9999999/fullTextXML")
    assert result["downloadable"] is True


def test_europepmc_lookup_without_pmcid_is_not_downloadable(database: Database) -> None:
    record = dict(EPMC_RECORD)
    del record["pmcid"]
    client = JsonHttpClient(
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
        provider="europepmc",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"resultList": {"result": [record]}})
        ),
        sleep=lambda _: None,
    )
    provider = EuropePmcProvider(database=database, client=client)
    assert provider.fetch_oa_location("10.1234/epmc.2026.1") is None


def test_europepmc_fetch_fulltext_returns_jats(database: Database) -> None:
    jats = (FIXTURES / "jats_article.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if "fullTextXML" in str(request.url):
            return httpx.Response(
                200, content=jats, headers={"Content-Type": "application/xml"}
            )
        return httpx.Response(200, json={"resultList": {"result": [EPMC_RECORD]}})

    client = JsonHttpClient(
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
        provider="europepmc",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    provider = EuropePmcProvider(database=database, client=client)
    result = provider.fetch_fulltext("10.1234/epmc.2026.1")
    assert result.format == "xml"
    assert result.provider == "europepmc"
    assert result.content == jats
    assert result.credential is None


def test_europepmc_fulltext_is_parsed_by_jats_parser(tmp_path: Path) -> None:
    """End to end: Europe PMC bytes land in the JATS parser, not Elsevier's."""
    from lit_harvest.services.normalization import NormalizationService
    from lit_harvest.storage.files import DocumentStorage

    database = Database(f"sqlite:///{tmp_path / 'state.db'}")
    database.initialize()
    from lit_harvest.models import PaperCreate

    paper = database.create_paper(PaperCreate(doi="10.1234/epmc.2026.1"))
    service = NormalizationService(database, DocumentStorage(tmp_path / "data"))
    result = service.normalize(
        content=(FIXTURES / "jats_article.xml").read_bytes(),
        doi="10.1234/epmc.2026.1",
        paper_id=paper.id,
        provider="europepmc",
        service="europepmc_fulltext",
        format="xml",
    )
    document = result["document"]
    assert document["provenance"]["provider"] == "europepmc"
    assert document["provenance"]["parser_version"] == "jats-xml/1.0"
    assert document["sections"]


# --------------------------------------------------------------- integration


def test_resolver_offers_free_epmc_fulltext_before_publisher(database: Database) -> None:
    client = JsonHttpClient(
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
        provider="europepmc",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"resultList": {"result": [EPMC_RECORD]}})
        ),
        sleep=lambda _: None,
    )
    epmc = EuropePmcProvider(database=database, client=client)

    class Publisher:
        name = "elsevier"
        display_name = "Elsevier"
        supports_fulltext = True
        fulltext_service = "article_retrieval"

    resolver = Resolver(ProviderRegistry([epmc, Publisher()]))
    candidates = resolver.candidates("10.1234/epmc.2026.1")
    # The free structured copy ranks ahead of every publisher route.
    assert candidates[0].free_access is True
    assert candidates[0].format == "xml"
    assert candidates[0].quality > max(item.quality for item in candidates[1:])


def test_new_providers_register_in_container(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={
                "crossref": CrossrefConfig(),
                "unpaywall": UnpaywallConfig(contact_email="a@b.org"),
                "europepmc": EuropePmcConfig(),
            }
        ),
    )
    container = ServiceContainer(config)
    names = set(container.providers.names())
    assert {"crossref", "unpaywall", "europepmc"} <= names
    # All three are key-free, so they must never ask for credentials.
    for provider in container.providers.all():
        assert provider.requires_credential is False


def test_container_keeps_new_providers_disabled_by_default(tmp_path: Path) -> None:
    config = AppConfig(
        storage=StorageConfig(root=tmp_path / "data"),
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
        providers=ProvidersConfig(
            entries={
                "crossref": CrossrefConfig(enabled=False),
                "europepmc": EuropePmcConfig(enabled=False),
            }
        ),
    )
    container = ServiceContainer(config)
    assert container.providers.names() == []


def test_crossref_tdm_lookup_does_not_send_select_on_single_work_route(
    database: Database,
) -> None:
    """Regression: the single-work route rejects `select` with HTTP 400.

    Only the works *search* route accepts `select`; sending it on
    `/works/{doi}` made every TDM lookup fail before this was fixed.
    """
    captured: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.url.params))
        return httpx.Response(200, json={"message": CROSSREF_WORK})

    client = JsonHttpClient(
        base_url="https://api.crossref.org",
        provider="crossref",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    provider = CrossrefProvider(database=database, client=client)
    links = provider.fetch_tdm_links("10.1016/j.mtcomm.2026.115551")
    assert links
    assert "select" not in captured[0]


# ------------------------------------------------- OA format detection


@pytest.mark.parametrize(
    ("content", "content_type", "expected"),
    [
        (b"%PDF-1.7 body", "", "pdf"),
        (b"<?xml version='1.0'?><root/>", "", "xml"),
        (b"<!DOCTYPE html><html></html>", "", "html"),
        (b"<html><body>x</body></html>", "", "html"),
        (b"<article><front/></article>", "", "xml"),
        (b"<div>x</div>", "", "html"),
        (b"plain text", "text/plain", None),
        (b"x", "application/xml", "xml"),
    ],
)
def test_oa_format_detection(content: bytes, content_type: str, expected: str | None) -> None:
    from lit_harvest.providers.oa import OpenAccessFetcher

    assert OpenAccessFetcher._detect_format(content, content_type) == expected


def test_jats_doctype_is_detected_as_xml_not_html() -> None:
    """Regression: JATS starts with an NLM DOCTYPE and used to be read as HTML.

    Misclassifying it sent structured XML to the HTML parser, silently
    producing an empty document instead of parsed sections.
    """
    from lit_harvest.providers.oa import OpenAccessFetcher

    jats = (FIXTURES / "jats_article.xml").read_bytes()
    assert OpenAccessFetcher._detect_format(jats, "application/xml") == "xml"

    fetcher = OpenAccessFetcher(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=jats, headers={"Content-Type": "application/xml"}
            )
        )
    )
    payload = fetcher.fetch("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML")
    assert payload["format"] == "xml"
    # And the bytes must actually reach the JATS parser.
    from lit_harvest.parsers import build_default_registry

    parsed = build_default_registry().parse(payload["content"], format=payload["format"])
    assert parsed.sections
    assert parsed.provenance.parser_version == "jats-xml/1.0"


def test_format_census_groups_downloads(tmp_path: Path) -> None:
    from lit_harvest.models import DownloadStatus, PaperCreate

    database = Database(f"sqlite:///{tmp_path / 'state.db'}")
    database.initialize()
    paper = database.create_paper(PaperCreate(doi="10.1/x"))
    for fmt, provider in [("xml", "europepmc"), ("pdf", "openaccess"), ("xml", "europepmc")]:
        database.record_download(
            paper_id=paper.id,
            provider=provider,
            service="s",
            credential_id=None,
            status=DownloadStatus.SUCCESS.value,
            format=fmt,
            raw_path=None,
            checksum="x",
        )
    census = {(row["provider"], row["format"]): row["count"] for row in database.format_census()}
    assert census[("europepmc", "xml")] == 2
    assert census[("openaccess", "pdf")] == 1


# ------------------------------------------------- routing safety


def test_hosted_record_provider_is_not_chosen_for_arbitrary_doi(
    database: Database,
) -> None:
    """Regression: Europe PMC must not hijack routing for paywalled DOIs.

    Europe PMC advertises `supports_fulltext`, but it can only serve records it
    hosts. Once it was registered alongside Elsevier it became
    `fulltext_providers()[0]` and every non-PMC DOI was routed to it, failing
    with "no record" instead of reaching the entitled publisher.
    """
    epmc = EuropePmcProvider(database=database)

    class Publisher:
        name = "elsevier"
        display_name = "Elsevier"
        supports_fulltext = True
        fulltext_service = "article_retrieval"

    # Registration order deliberately puts the conditional provider first.
    resolver = Resolver(ProviderRegistry([epmc, Publisher()]))
    route = resolver.route_for_job("10.1016/j.mtcomm.2026.115551")
    assert route is not None
    assert route.provider == "elsevier"


def test_hosted_record_provider_is_used_when_it_is_the_only_option(
    database: Database,
) -> None:
    """With nothing else configured, a best-effort attempt is still made."""
    route = Resolver(ProviderRegistry([EuropePmcProvider(database=database)])).route_for_job(
        "10.1234/whatever"
    )
    assert route is not None
    assert route.provider == "europepmc"


def test_europepmc_declares_hosted_record_constraint() -> None:
    provider = EuropePmcProvider(database=Database("sqlite:///:memory:"))
    assert provider.fulltext_requires_hosted_record is True
