"""The concise v0.4 user journey: bootstrap once, then work through an Agent."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.mcp.server import TOOL_NAMES

runner = CliRunner()


def test_install_print_config_and_agent_tool_contract(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILLCHECK_HOME", str(tmp_path / "state"))
    result = runner.invoke(app, ["install", "--target", "codex", "--print-config", "codex"])

    assert result.exit_code == 0
    assert "skillcheck" in result.stdout
    assert TOOL_NAMES == {"skillcheck_analyze", "skillcheck_evidence", "skillcheck_save_review"}
