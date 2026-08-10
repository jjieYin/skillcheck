from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app


runner = CliRunner()


def test_uninstall_command_requires_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "skillcheck.commands.uninstall.build_uninstall_context",
        lambda: SimpleNamespace(),
    )
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 3
    assert "卸载失败" in result.output
