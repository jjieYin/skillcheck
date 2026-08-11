from __future__ import annotations

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.database import CatalogDatabase
from skillcheck.config import AppConfig, save_config

runner = CliRunner()


def test_no_args_starts_install_when_not_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SKILLCHECK_HOME", str(tmp_path / "state"))

    result = runner.invoke(app, [], input="n\n")

    assert result.exit_code == 0
    assert "配置 Skillcheck Agent 接入" in result.stdout


def test_no_args_shows_status_when_initialized(monkeypatch, tmp_path) -> None:
    home = tmp_path / "state"
    monkeypatch.setenv("SKILLCHECK_HOME", str(home))
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.initialized = True
    config.targets.configured = ["codex"]
    CatalogDatabase(config.catalog.database_path).initialize()
    save_config(home / "config.yaml", config)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "已接入 Agent" in result.stdout
    assert "请在 Agent 中直接提出 Skills 检查需求" in result.stdout
