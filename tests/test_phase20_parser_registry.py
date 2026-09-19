"""Multi-format parser dispatch: registry selection and each parser."""

from pathlib import Path

import pytest

from lit_harvest.parsers import (
    ParserRegistry,
    UnsupportedFormatError,
    build_default_registry,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def registry() -> ParserRegistry:
    return build_default_registry()


# --------------------------------------------------------------- registry


def test_registry_selects_elsevier_for_science_direct_xml() -> None:
    registry = build_default_registry()
    content = (FIXTURES / "science_direct_full.xml").read_bytes()
    parser = registry.select(content, format="xml", provider="elsevier")
    assert parser.name == "elsevier_full_xml"


def test_registry_selects_jats_for_jats_xml() -> None:
    registry = build_default_registry()
    content = (FIXTURES / "jats_article.xml").read_bytes()
    assert registry.select(content, format="xml").name == "jats"


def test_registry_selects_pdf_parser_for_pdf() -> None:
    registry = build_default_registry()
    content = (FIXTURES / "pdf_text_layer.pdf").read_bytes()
    assert registry.select(content, format="pdf").name == "pdf_text_layer"


def test_registry_rejects_unsupported_format() -> None:
    registry = build_default_registry()
    with pytest.raises(UnsupportedFormatError):
        registry.select(b"not a document", format="docx")


def test_registry_prefers_provider_parser_when_it_matches() -> None:
    """An Elsevier payload must not be stolen by the generic JATS parser."""
    registry = build_default_registry()
    content = (FIXTURES / "science_direct_full.xml").read_bytes()
    parser = registry.select(content, format="xml", provider="elsevier")
    assert parser.name == "elsevier_full_xml"


def test_registry_falls_back_when_provider_hint_does_not_match() -> None:
    """A provider hint must not force a parser that rejects the content."""
    registry = build_default_registry()
    content = (FIXTURES / "jats_article.xml").read_bytes()
    parser = registry.select(content, format="xml", provider="elsevier")
    assert parser.name == "jats"


def test_registry_candidates_are_format_scoped(registry: ParserRegistry) -> None:
    xml_names = {p.name for p in registry.candidates(format="xml")}
    assert "jats" in xml_names
    assert "pdf_text_layer" not in xml_names


# ------------------------------------------------------------- JATS parser


def test_jats_extracts_bibliographic_metadata() -> None:
    registry = build_default_registry()
    document = registry.parse(
        (FIXTURES / "jats_article.xml").read_bytes(),
        format="xml",
        provider="europepmc",
    )
    assert document.identifiers.doi == "10.1234/jtm.2026.001"
    assert document.identifiers.pmid == "12345678"
    assert document.identifiers.publisher_specific["pmcid"] == "PMC9999999"
    assert document.bibliographic.title == "Solid-state battery interfaces under thermal cycling"
    assert document.bibliographic.journal == "Journal of Test Materials"
    assert document.bibliographic.issn == "1234-5678"
    assert document.bibliographic.volume == "42"
    assert document.bibliographic.issue == "3"
    assert document.bibliographic.publisher == "Test Publishers"
    assert document.bibliographic.document_type == "research-article"


def test_jats_extracts_dates_authors_and_affiliations() -> None:
    document = build_default_registry().parse(
        (FIXTURES / "jats_article.xml").read_bytes(), format="xml"
    )
    assert document.dates.received == "2026-01-02"
    assert document.dates.accepted == "2026-02-11"
    assert document.dates.online == "2026-02-12"
    assert len(document.authors) == 2
    assert document.authors[0].given_name == "Wei"
    assert document.authors[0].surname == "Li"
    assert document.authors[0].orcid == "0000-0002-1234-5678"
    assert document.authors[0].email == "wei.li@example.org"
    assert len(document.affiliations) == 2
    assert document.affiliations[0].name == "Harbin Institute of Technology"


def test_jats_extracts_sections_tables_equations_and_references() -> None:
    document = build_default_registry().parse(
        (FIXTURES / "jats_article.xml").read_bytes(), format="xml"
    )
    assert document.abstract is not None
    assert "Thermal cycling" in document.abstract
    assert document.keywords == ["solid-state battery", "interface"]
    assert [s.title for s in document.sections] == ["Introduction", "Results"]
    assert document.sections[0].children[0].title == "Background"
    assert document.sections[1].paragraphs[0].text.startswith("Resistance rose")
    assert document.tables[0].rows[1] == ["A", "3.2"]
    assert document.equations[0].mathml is not None
    assert document.references[0].doi == "10.1000/ref"


def test_jats_records_open_access_license() -> None:
    document = build_default_registry().parse(
        (FIXTURES / "jats_article.xml").read_bytes(), format="xml"
    )
    assert document.open_access.is_open_access is True
    assert document.open_access.license == "open-access"
    assert document.provenance.parser_version == "jats-xml/1.0"
    assert document.provenance.sha256


def test_jats_parser_is_deterministic() -> None:
    content = (FIXTURES / "jats_article.xml").read_bytes()
    parser = build_default_registry()
    first = parser.parse(content, format="xml")
    second = parser.parse(content, format="xml")
    first.provenance.acquired_at = second.provenance.acquired_at
    assert first == second


# ------------------------------------------------------------- HTML parser


HTML_ARTICLE = b"""<!DOCTYPE html>
<html><head>
<meta name="citation_title" content="Interface stability in solid electrolytes">
<meta name="citation_doi" content="10.5555/html.2026.7">
<meta name="citation_journal_title" content="Journal of HTML Testing">
<meta name="citation_author" content="Ada Lovelace">
<meta name="citation_abstract" content="A short abstract about interfaces.">
<meta name="citation_keywords" content="battery, interface">
</head><body><article>
<h2>Introduction</h2>
<p>Solid electrolytes can suppress dendrite growth in cells.</p>
<h2>Methods</h2>
<p>Samples were cycled at elevated temperature.</p>
<figure id="f1"><img src="https://example.org/fig1.png" alt="plot"/>
<figcaption>Fig 1. Conductivity versus temperature.</figcaption></figure>
</article></body></html>
"""


def test_html_parser_reads_citation_meta_tags() -> None:
    document = build_default_registry().parse(HTML_ARTICLE, format="html")
    assert document.identifiers.doi == "10.5555/html.2026.7"
    assert document.bibliographic.title == "Interface stability in solid electrolytes"
    assert document.bibliographic.journal == "Journal of HTML Testing"
    assert document.authors[0].full_name == "Ada Lovelace"
    assert document.keywords == ["battery", "interface"]
    assert "interfaces" in (document.abstract or "")


def test_html_parser_extracts_sections_and_figures() -> None:
    document = build_default_registry().parse(HTML_ARTICLE, format="html")
    assert [s.title for s in document.sections] == ["Introduction", "Methods"]
    assert document.sections[0].paragraphs[0].text.startswith("Solid electrolytes")
    assert document.figures[0].images[0]["url"] == "https://example.org/fig1.png"
    assert "Conductivity" in (document.figures[0].caption or "")


def test_html_parser_tolerates_minimal_document() -> None:
    document = build_default_registry().parse(b"<html><body></body></html>", format="html")
    assert document.sections == []
    assert document.authors == []


# -------------------------------------------------------------- PDF parser


def test_pdf_parser_extracts_text_layer() -> None:
    document = build_default_registry().parse(
        (FIXTURES / "pdf_text_layer.pdf").read_bytes(),
        format="pdf",
        provider="openaccess",
    )
    # A DOI in the text layer is recovered without any external lookup.
    assert document.identifiers.doi == "10.1234/jtm.2026.001"
    text = " ".join(p.text for s in document.sections for p in s.paragraphs)
    assert "interfacial resistance" in text
    assert document.provenance.format == "pdf"
    assert document.provenance.parser_version == "pdf-text-layer/1.0"


def test_pdf_parser_marks_image_only_pdf_as_needing_ocr() -> None:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    document = build_default_registry().parse(buffer.getvalue(), format="pdf")
    # A blank (image-only) PDF has no text layer: it must be flagged, not faked.
    assert document.sections == []
    assert any(item.kind == "needs_ocr" for item in document.attachments)


def test_pdf_parser_never_raises_on_corrupt_input() -> None:
    """A malformed PDF yields an empty document, not an exception."""
    document = build_default_registry().parse(b"%PDF-1.7\ngarbage", format="pdf")
    assert any(item.kind == "needs_ocr" for item in document.attachments)


# ------------------------------------------------- normalization service


def test_normalization_service_dispatches_jats(tmp_path: Path) -> None:
    from lit_harvest.models import PaperCreate
    from lit_harvest.services.normalization import NormalizationService
    from lit_harvest.storage.database import Database
    from lit_harvest.storage.files import DocumentStorage

    database = Database(f"sqlite:///{tmp_path / 'state.db'}")
    database.initialize()
    storage = DocumentStorage(tmp_path / "data")
    paper = database.create_paper(PaperCreate(doi="10.1234/jtm.2026.001"))
    service = NormalizationService(database, storage)

    result = service.normalize(
        content=(FIXTURES / "jats_article.xml").read_bytes(),
        doi="10.1234/jtm.2026.001",
        paper_id=paper.id,
        provider="europepmc",
        service="europepmc_fulltext",
        format="xml",
    )
    assert result["document"]["bibliographic"]["journal"] == "Journal of Test Materials"
    assert result["document"]["provenance"]["parser_version"] == "jats-xml/1.0"


def test_normalization_service_can_normalize_reports_support() -> None:
    from lit_harvest.services.normalization import NormalizationService
    from lit_harvest.storage.database import Database
    from lit_harvest.storage.files import DocumentStorage

    service = NormalizationService(Database("sqlite:///:memory:"), DocumentStorage(Path("/tmp")))
    assert service.can_normalize(format="xml", content=(FIXTURES / "jats_article.xml").read_bytes())
    assert service.can_normalize(format="pdf", content=b"%PDF-1.7")
    assert not service.can_normalize(format="docx", content=b"whatever")
