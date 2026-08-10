from typer.testing import CliRunner

from skillcheck.app.main import app


runner = CliRunner()


def test_no_args_opens_menu(monkeypatch) -> None:
    monkeypatch.setattr("skillcheck.app.menu.choose_action", lambda: "0")
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "扫描现有 Skills" in result.stdout
