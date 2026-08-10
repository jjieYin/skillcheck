from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


def test_upgrade_command_uses_manager(monkeypatch) -> None:
    class FakeManager:
        def __init__(self, context): pass
        def install(self, version): return SimpleNamespace(changed=True, message="升级完成")
        def rollback(self): return SimpleNamespace(changed=True, message="回滚完成")

    monkeypatch.setattr("skillcheck.commands.upgrade.UpgradeManager", FakeManager)
    monkeypatch.setattr("skillcheck.commands.upgrade.build_upgrade_context", lambda: object())
    result = runner.invoke(app, ["upgrade", "0.4.0-beta"])
    assert result.exit_code == 0
    assert "升级完成" in result.stdout

