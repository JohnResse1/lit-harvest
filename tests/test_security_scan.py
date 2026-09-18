from pathlib import Path

from lit_harvest.security import scan_repository


def test_security_scan_allows_placeholders(tmp_path: Path) -> None:
    (tmp_path / "config.example.yaml").write_text(
        "secret_ref: file:elsevier:primary\n# placeholder example, replace-with-your-own-key\n",
        encoding="utf-8",
    )
    report = scan_repository(tmp_path)
    assert report.ok is True


def test_security_scan_detects_assigned_elsevier_key(tmp_path: Path) -> None:
    key = "a" * 32
    (tmp_path / "leaked.py").write_text(f'X_ELS_APIKey = "{key}"\n', encoding="utf-8")
    report = scan_repository(tmp_path)
    assert report.ok is False
    assert report.findings[0].kind == "Elsevier API key assignment"


def test_security_scan_detects_private_key_block(tmp_path: Path) -> None:
    (tmp_path / "cert.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nnot-real\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    report = scan_repository(tmp_path)
    assert report.ok is False
    assert any(item.kind == "Private key block" for item in report.findings)
