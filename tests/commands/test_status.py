from __future__ import annotations

import json

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.database import CatalogDatabase
from skillcheck.config import AppConfig, save_config

runner = CliRunner()


def test_status_is_structured_and_uninitialized_is_not_an_error(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    config = AppConfig.default(home=tmp_path / "home")
    save_config(state / "config.yaml", config)

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["configured_agents"] == []
    assert payload["initialized"] is False
    assert payload["root_count"] == 0
    assert payload["skill_count"] == 0
    assert payload["watch_mode"] == "on_mcp_connection"


def test_status_reads_catalog_counts_and_latest_sync(monkeypatch, tmp_path) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.initialized = True
    config.targets.configured = ["codex", "claude"]
    database = CatalogDatabase(config.catalog.database_path)
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO sync_events
            (event_id, revision, started_at, completed_at, added, updated, removed, invalid, warnings_json)
            VALUES ('event-1', 'sync-1', '2026-08-10T00:00:00+00:00',
                    '2026-08-10T00:01:00+00:00', 0, 0, 0, 0, '[]')"""
        )
    save_config(state / "config.yaml", config)

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["configured_agents"] == ["codex", "claude"]
    assert payload["initialized"] is True
    assert payload["revision"] == "sync-1"
    assert payload["last_sync"] == "2026-08-10T00:01:00Z"
