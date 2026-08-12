import json
from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.commands.install import _persist_configured_targets
from skillcheck.config import load_config
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
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda *_args, **_kwargs: pipeline)

    result = runner.invoke(app, ["install", "--print-config", "codex"])

    assert result.exit_code == 0
    assert "mcp_servers" in result.stdout
    assert not (tmp_path / "config.toml").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_print_config_with_missing_config_is_read_only(tmp_path: Path) -> None:
    config = tmp_path / "missing.yaml"
    runner_result = runner.invoke(
        app,
        ["install", "--print-config", "codex", "--config", str(config)],
    )

    assert runner_result.exit_code == 0
    assert not config.exists()
    assert not (tmp_path / ".skillcheck").exists()


def test_install_accepts_multiple_agents_and_prints_exact_paths(monkeypatch, tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    monkeypatch.setenv("SKILLCHECK_HOME", str(tmp_path / "state"))
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda *_args, **_kwargs: pipeline)

    result = runner.invoke(app, ["install", "--target", "codex", "--location", "global", "--yes"])

    assert result.exit_code == 0
    assert str(tmp_path / "config.toml") in result.stdout
    assert str(tmp_path / "AGENTS.md") in result.stdout
    assert (tmp_path / "config.toml").exists()
    assert (tmp_path / "AGENTS.md").exists()


def test_successful_install_persists_agents_for_status(monkeypatch, tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    config = tmp_path / "state" / "config.yaml"
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda *_args, **_kwargs: pipeline)

    installed = runner.invoke(
        app,
        ["install", "--target", "codex", "--location", "global", "--yes", "--config", str(config)],
    )
    status = runner.invoke(app, ["status", "--config", str(config), "--json"])

    assert installed.exit_code == 0
    assert json.loads(status.stdout)["configured_agents"] == ["codex"]
    assert json.loads(status.stdout)["initialized"] is False


def test_cancelled_install_does_not_create_configuration(monkeypatch, tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    config = tmp_path / "state" / "config.yaml"
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda *_args, **_kwargs: pipeline)

    result = runner.invoke(app, ["install", "--target", "codex", "--config", str(config)])

    assert result.exit_code == 0
    assert not config.exists()


def test_persisted_agent_selection_is_replaced_not_appended(tmp_path: Path) -> None:
    config = tmp_path / "state" / "config.yaml"
    config.parent.mkdir()
    loaded = load_config(config, home=tmp_path)
    loaded.targets.configured = ["codex", "claude"]
    from skillcheck.config import save_config

    save_config(config, loaded)

    _persist_configured_targets(config, ["codex"], "global")

    saved = load_config(config, home=tmp_path, create=False)
    assert saved.targets.configured == ["codex"]
    assert saved.targets.selection_initialized is True


def test_install_without_target_requires_an_interactive_picker(monkeypatch, tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    config = tmp_path / "state" / "config.yaml"
    monkeypatch.setattr("skillcheck.commands.install.build_install_pipeline", lambda *_args, **_kwargs: pipeline)

    result = runner.invoke(app, ["install", "--config", str(config)])

    assert result.exit_code == 2
    assert "interactive terminal required" in result.output
