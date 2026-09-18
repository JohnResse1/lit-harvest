from pathlib import Path

from typer.testing import CliRunner

from lit_harvest.cli import app


def test_cli_help_and_version() -> None:
    runner = CliRunner()
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "doctor" in help_result.stdout
    assert "search" in help_result.stdout
    version_result = runner.invoke(app, ["version"])
    assert version_result.exit_code == 0
    assert "0.1.0" in version_result.stdout


def test_cli_doctor_offline(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
storage:
  root: {tmp_path / "data"}
database:
  url: sqlite:///{tmp_path / "state.db"}
providers:
  elsevier:
    enabled: true
    credentials: []
""",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["doctor", "--config", str(config), "--json"])
    assert result.exit_code == 1
    assert '"database"' in result.stdout
    assert '"ok": true' in result.stdout
