from pathlib import Path

import pytest

from lit_harvest.input.doi_loader import load_dois, load_single_doi, validate_doi


def test_validate_doi_variants() -> None:
    for value in (
        "10.1016/j.xxx",
        " doi:10.1016/j.xxx ",
        "https://doi.org/10.1016/j.xxx",
        "http://dx.doi.org/10.1016/j.xxx",
        "DOI: 10.1016/j.xxx",
    ):
        ok, normalized = validate_doi(value)
        assert ok, value
        assert normalized == "10.1016/j.xxx"


def test_csv_import_preserves_first_seen_and_logs_invalid(tmp_path: Path) -> None:
    path = tmp_path / "papers.csv"
    path.write_text(
        "title,doi\nOne,10.1000/A\nDuplicate,https://doi.org/10.1000/a\nBad,not-a-doi\n"
        "Two,doi:10.1000/b\n",
        encoding="utf-8",
    )
    result = load_dois(path, doi_column="DOI")
    assert [item.doi for item in result.valid] == ["10.1000/a", "10.1000/b"]
    assert len(result.invalid) == 1
    assert result.invalid[0].source_row == 4
    assert "shape" in result.invalid[0].reason


def test_jsonl_and_json_import(tmp_path: Path) -> None:
    jsonl = tmp_path / "papers.jsonl"
    jsonl.write_text(
        '{"doi": "10.1000/a"}\n{"DOI": "10.1000/b"}\n{"other": "10.1000/c"}\n',
        encoding="utf-8",
    )
    result = load_dois(jsonl)
    assert [item.doi for item in result.valid] == ["10.1000/a", "10.1000/b"]

    json_file = tmp_path / "papers.json"
    json_file.write_text(
        '{"items": [{"doi": "10.1000/a"}, {"doi": "10.1000/c"}]}',
        encoding="utf-8",
    )
    result = load_dois(json_file)
    assert [item.doi for item in result.valid] == ["10.1000/a", "10.1000/c"]


def test_txt_import_keeps_order_and_deduplicates(tmp_path: Path) -> None:
    path = tmp_path / "papers.txt"
    path.write_text("10.1000/a\n\n10.1000/b\n10.1000/a\ninvalid\n", encoding="utf-8")
    result = load_dois(path)
    assert [item.doi for item in result.valid] == ["10.1000/a", "10.1000/b"]
    assert result.valid[0].source_row == 1
    assert len(result.invalid) == 1


def test_single_doi_rejects_invalid() -> None:
    assert load_single_doi("https://doi.org/10.1000/x") == "10.1000/x"
    with pytest.raises(ValueError, match="shape"):
        load_single_doi("not-a-doi")
