from typer.testing import CliRunner

from skillcheck.cli import app


runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "skillcheck 0.1.0" in result.stdout
