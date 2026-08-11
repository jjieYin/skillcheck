from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.commands.uninstall import _windows_removal_command, build_uninstall_context
from skillcheck.lifecycle.uninstall import UninstallManager

runner = CliRunner()


def test_uninstall_command_reports_invalid_context(monkeypatch) -> None:
    monkeypatch.setattr(
        "skillcheck.commands.uninstall.build_uninstall_context",
        lambda: SimpleNamespace(),
    )
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 3
    assert "uninstall failed" in result.output


def test_complete_uninstall_removes_only_owned_program_and_data(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    program_root = tmp_path / "local-app-data" / "skillcheck"
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setattr("skillcheck.commands.uninstall._remove_windows_user_path_entry", lambda _path: None)
    (program_root / "versions" / "0.4.0").mkdir(parents=True)
    (program_root / "bin").mkdir()
    (program_root / "bin" / "skillcheck.cmd").write_text("launcher", encoding="utf-8")
    (state / "reports").mkdir(parents=True)
    (state / "config.yaml").write_text("schema_version: 4\ncatalog: {}\n", encoding="utf-8")
    user_skill = tmp_path / "user-skills" / "SKILL.md"
    user_skill.parent.mkdir()
    user_skill.write_text("keep", encoding="utf-8")

    manager = UninstallManager(build_uninstall_context())
    result = manager.execute(manager.plan(complete=True), confirmed=True)

    assert result.changed is True
    assert not program_root.exists()
    assert not state.exists()
    assert user_skill.read_text(encoding="utf-8") == "keep"


def test_complete_uninstall_keep_cli_preserves_program_files(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    program_root = tmp_path / "local-app-data" / "skillcheck"
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    (program_root / "versions").mkdir(parents=True)
    state.mkdir()

    manager = UninstallManager(build_uninstall_context())
    plan = manager.plan(complete=True, keep_cli=True)
    manager.execute(plan, confirmed=True)

    assert plan.program_paths == []
    assert program_root.exists()
    assert not state.exists()


def test_windows_deferred_removal_command_also_cleans_owned_path_entry(tmp_path: Path) -> None:
    command = _windows_removal_command(tmp_path / "skillcheck", tmp_path / "skillcheck" / "bin")

    assert "Remove-Item -LiteralPath" in command
    assert "GetEnvironmentVariable('Path', 'User')" in command
    assert "SetEnvironmentVariable('Path'" in command
    assert str(tmp_path / "skillcheck" / "bin") in command
