from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


def test_uninstall_command_reports_invalid_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "skillcheck.commands.uninstall.build_uninstall_context",
        lambda: SimpleNamespace(),
    )
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 3
    assert "uninstall failed" in result.output
