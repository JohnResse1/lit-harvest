from pathlib import Path


def test_frontend_build_is_packaged() -> None:
    static = Path(__file__).parents[1] / "src" / "lit_harvest" / "api" / "static"
    index = static / "index.html"
    assert index.exists()
    html = index.read_text(encoding="utf-8")
    assert "Literature Harvester" in html
    assert "assets/" in html
    assert any((static / "assets").glob("*.js"))
    assert any((static / "assets").glob("*.css"))
