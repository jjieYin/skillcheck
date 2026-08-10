from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.pipelines.install_pipeline import InstallPipeline
from skillcheck.targets.base import AgentId
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.registry import TargetRegistry

runner = CliRunner()


def _pipeline(tmp_path: Path) -> InstallPipeline:
    target = CodexTarget(
        global_config=tmp_path / "config.toml",
        project_config=tmp_path / "project" / "config.toml",
        global_instructions=tmp_path / "AGENTS.md",
        project_instructions=tmp_path / "project" / "AGENTS.md",
    )
    return InstallPipeline(TargetRegistry({AgentId.CODEX: target}), smoke_check=lambda: "smoke passed")


def test_print_config_does_not_write_files(monkeypatch, tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda _: pipeline)

    result = runner.invoke(app, ["install", "--print-config", "codex"])

    assert result.exit_code == 0
    assert "mcp_servers" in result.stdout
    assert not (tmp_path / "config.toml").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_install_accepts_multiple_agents_and_prints_exact_paths(monkeypatch, tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda _: pipeline)

    result = runner.invoke(app, ["install", "--target", "codex", "--location", "global", "--yes"])

    assert result.exit_code == 0
    assert str(tmp_path / "config.toml") in result.stdout
    assert str(tmp_path / "AGENTS.md") in result.stdout
    assert (tmp_path / "config.toml").exists()
    assert (tmp_path / "AGENTS.md").exists()
