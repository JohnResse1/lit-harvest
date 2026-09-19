"""PDF storage naming and reuse, including hand-added PDFs."""

from pathlib import Path

import pytest

from lit_harvest.config import (
    AppConfig,
    DatabaseConfig,
    ElsevierConfig,
    ProvidersConfig,
    StorageConfig,
)
from lit_harvest.models import PaperCreate
from lit_harvest.services.container import ServiceContainer
from lit_harvest.storage.files import DocumentStorage

DOI = "10.1016/j.mtcomm.2026.115551"


@pytest.fixture
def storage(tmp_path: Path) -> DocumentStorage:
    store = DocumentStorage(tmp_path / "data")
    store.ensure_layout()
    return store


# --------------------------------------------------------------- naming


def test_pdf_filename_is_provider_scoped(storage: DocumentStorage) -> None:
    assert storage.pdf_filename("elsevier") == "elsevier_pdf.pdf"
    assert storage.pdf_filename("springer") == "springer_pdf.pdf"


def test_pdf_filename_falls_back_when_provider_is_unknown(
    storage: DocumentStorage,
) -> None:
    assert storage.pdf_filename(None) == "publisher_pdf.pdf"
    assert storage.pdf_filename("") == "publisher_pdf.pdf"


def test_pdf_filename_is_filesystem_safe(storage: DocumentStorage) -> None:
    # A provider label must never be able to escape the raw directory.
    name = storage.pdf_filename("../evil name")
    assert "/" not in name
    assert name.endswith("_pdf.pdf")


# ------------------------------------------------------------ discovery


def test_find_pdf_returns_none_when_absent(storage: DocumentStorage) -> None:
    assert storage.find_pdf(DOI) is None


def test_find_pdf_finds_a_hand_added_file(storage: DocumentStorage) -> None:
    """A PDF the user placed manually must be discovered by extension.

    Regression: discovery used to be the hardcoded name `elsevier_pdf.pdf`, so a
    hand-added PDF was invisible and the tool downloaded a duplicate.
    """
    written = storage.write_raw(DOI, "manually_downloaded_2026.pdf", b"%PDF-1.7 hand")
    assert storage.find_pdf(DOI) == written


def test_find_pdf_prefers_publisher_over_open_access(storage: DocumentStorage) -> None:
    storage.write_raw(DOI, "openaccess.pdf", b"%PDF-1.7 oa")
    publisher = storage.write_raw(DOI, "elsevier_pdf.pdf", b"%PDF-1.7 pub")
    assert storage.find_pdf(DOI) == publisher


def test_find_pdf_ignores_non_pdf_files(storage: DocumentStorage) -> None:
    storage.write_raw(DOI, "elsevier_xml.xml", b"<root/>")
    assert storage.find_pdf(DOI) is None


# -------------------------------------------------------------- reuse


def container_for(tmp_path: Path) -> ServiceContainer:
    return ServiceContainer(
        AppConfig(
            storage=StorageConfig(root=tmp_path / "data"),
            database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'state.db'}"),
            providers=ProvidersConfig(entries={"elsevier": ElsevierConfig()}),
        )
    )


def test_fetch_pdf_reuses_hand_added_pdf_without_network(tmp_path: Path) -> None:
    container = container_for(tmp_path)
    paper = container.database.create_paper(PaperCreate(doi=DOI))
    hand = container.storage.write_raw(DOI, "my_download.pdf", b"%PDF-1.7 hand")

    result = container.acquisition.fetch_pdf(paper.id)
    assert result["reused"] is True
    assert result["pdf_path"] == str(hand)


def test_hand_added_pdf_works_without_a_pdf_capable_provider(tmp_path: Path) -> None:
    """Reuse is checked before provider lookup.

    A user who supplies their own PDF should not be blocked just because no
    PDF-capable provider is configured.
    """
    container = container_for(tmp_path)
    # Remove every PDF-capable provider from the registry.
    container.providers._providers = {
        name: provider
        for name, provider in container.providers._providers.items()
        if not getattr(provider, "supports_pdf", False)
    }
    paper = container.database.create_paper(PaperCreate(doi=DOI))
    hand = container.storage.write_raw(DOI, "my_download.pdf", b"%PDF-1.7 hand")

    result = container.acquisition.fetch_pdf(paper.id)
    assert result["reused"] is True
    assert result["pdf_path"] == str(hand)


def test_missing_pdf_without_provider_explains_the_manual_option(
    tmp_path: Path,
) -> None:
    from lit_harvest.providers.base import ProviderUnavailableError

    container = container_for(tmp_path)
    container.providers._providers = {}
    paper = container.database.create_paper(PaperCreate(doi=DOI))

    with pytest.raises(ProviderUnavailableError) as excinfo:
        container.acquisition.fetch_pdf(paper.id)
    # The error should tell a non-developer what to do instead.
    assert "raw/" in str(excinfo.value)
