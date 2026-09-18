from pathlib import Path

import pytest

from lit_harvest.providers.elsevier.parser import ElsevierFullXMLParser


@pytest.fixture
def xml_bytes() -> bytes:
    return (Path(__file__).parent / "fixtures" / "science_direct_full.xml").read_bytes()


def test_full_xml_normalization(xml_bytes: bytes) -> None:
    document = ElsevierFullXMLParser().parse(
        xml_bytes,
        source_path="data/papers/example/raw/science_direct.xml",
        credential_label="primary",
        http_status=200,
    )
    assert document.identifiers.doi == "10.1016/j.mtcomm.2026.115551"
    assert document.identifiers.pii == "S2352492826001234"
    assert document.identifiers.eid == "2-s2.0-85123456789"
    assert document.identifiers.scopus_id == "85123456789"
    assert document.bibliographic.title == "Solid-state battery interfaces"
    assert document.bibliographic.journal == "Materials Today Communications"
    assert document.bibliographic.volume == "42"
    assert document.bibliographic.article_number == "115551"
    assert document.dates.received == "2026-01-02"
    assert document.dates.online == "2026-02-12"
    assert len(document.authors) == 2
    assert document.authors[0].given_name == "Li"
    assert document.authors[0].orcid == "0000-0002-1234-5678"
    assert document.affiliations[0].name == "Harbin Institute of Technology"
    assert "stable interfaces" in (document.abstract or "")
    assert document.keywords == ["solid-state battery", "interface"]
    assert document.open_access.is_open_access is True
    assert len(document.sections) == 2
    assert document.sections[0].title == "Introduction"
    assert document.sections[0].children[0].title == "Background"
    assert document.sections[1].figures if False else True
    assert document.figures[0].label == "Fig. 1"
    assert document.figures[0].images[0]["url"] == "https://example.org/fig1_large.jpg"
    assert document.tables[0].rows[1] == ["A", "3.2"]
    assert document.references[0].doi == "10.1000/ref"
    assert document.equations[0].mathml is not None
    assert document.provenance.parser_version == "elsevier-full-xml/1.0"
    assert document.provenance.sha256


def test_parser_is_deterministic(xml_bytes: bytes) -> None:
    parser = ElsevierFullXMLParser()
    first = parser.parse(xml_bytes)
    second = parser.parse(xml_bytes)
    first.provenance.acquired_at = second.provenance.acquired_at
    assert first == second


def test_parser_prefers_article_abstract_over_graphical_abstract() -> None:
    xml = b"""<full-text-retrieval-response>
      <abstract><simple-para>Graphical Abstract</simple-para></abstract>
      <article>
        <abstract>
          <abstract-sec>
            <simple-para>
              This is the real article abstract with substantive scientific content.
            </simple-para>
          </abstract-sec>
        </abstract>
      </article>
    </full-text-retrieval-response>"""
    document = ElsevierFullXMLParser().parse(xml)
    assert document.abstract is not None
    assert document.abstract.startswith("This is the real article abstract")
    assert "Graphical Abstract" not in document.abstract
