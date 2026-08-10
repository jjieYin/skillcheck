from typer.testing import CliRunner

from skillcheck.app.main import app


runner = CliRunner()


def test_v2_root_app_exposes_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("skillcheck ")
