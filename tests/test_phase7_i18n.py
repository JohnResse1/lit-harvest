from pathlib import Path


def test_frontend_contains_chinese_translations() -> None:
    source = (Path(__file__).parents[1] / "frontend" / "src" / "lib" / "i18n.ts").read_text(
        encoding="utf-8"
    )
    required = [
        "总览",
        "文献",
        "提供商",
        "失败任务",
        "配额余量",
        "队列已暂停",
        "本地优先",
    ]
    for text in required:
        assert text in source


def test_built_frontend_is_bilingual_capable() -> None:
    static = Path(__file__).parents[1] / "src" / "lit_harvest" / "api" / "static"
    bundle = next((static / "assets").glob("*.js")).read_text(encoding="utf-8")
    assert "总览" in bundle
    assert "Overview" in bundle


def test_frontend_parses_structured_api_errors() -> None:
    source = (Path(__file__).parents[1] / "frontend" / "src" / "lib" / "api.ts").read_text(
        encoding="utf-8"
    )
    assert "extractErrorMessage" in source
    # Raw response text must not be surfaced verbatim to users.
    assert "throw new Error(detail ||" not in source
