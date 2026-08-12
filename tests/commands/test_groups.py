from __future__ import annotations

import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import AppConfig, save_config
from skillcheck.governance.analyzer import GovernanceAnalyzer

runner = CliRunner()


def _snapshot(skill_id: str, root_id: str, provider: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}",
        skill_id=skill_id,
        root_id=root_id,
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        description="API review",
        body="Review API contracts.",
        content_hash="sha256:mirror",
        indexed_at=datetime.now(UTC),
    )


def _configured(tmp_path):
    state = tmp_path / "state"
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.initialized = True
    config.catalog.database_path = state / "catalog.db"
    config.reports.directory = state / "reports"
    save_config(state / "config.yaml", config)
    database = CatalogDatabase(config.catalog.database_path)
    database.initialize()
    catalog = CatalogRepository(database)
    for root_id, provider in (("codex-root", "codex"), ("claude-root", "claude")):
        catalog.upsert_root(
            LibraryRoot(root_id=root_id, path=tmp_path / root_id, provider=provider, scope=RootScope.GLOBAL)
        )
    catalog.upsert_snapshot(_snapshot("codex-api", "codex-root", "codex"))
    catalog.upsert_snapshot(_snapshot("claude-api", "claude-root", "claude"))
    return state, catalog


def test_groups_list_shows_status(tmp_path, monkeypatch) -> None:
    state, catalog = _configured(tmp_path)
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    analyzer = GovernanceAnalyzer(catalog)
    result = analyzer.analyze_library(limit=20)
    from skillcheck.governance.sync_groups import SyncGroupService

    group = next(item for item in result.groups if item.relation.value == "MIRRORED_COPY")
    SyncGroupService(catalog).create_from_analysis(
        run_id=result.run_id,
        group_id=group.group_id,
        name="api-review",
        authority_skill_id="codex-api",
        member_skill_ids=["claude-api"],
    )
    listed = runner.invoke(app, ["groups", "list", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)[0]["status"] == "IN_SYNC"


def test_groups_remove_deletes_only_metadata(tmp_path, monkeypatch) -> None:
    state, catalog = _configured(tmp_path)
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    analyzer = GovernanceAnalyzer(catalog)
    result = analyzer.analyze_library(limit=20)
    from skillcheck.governance.sync_groups import SyncGroupService

    candidate = next(item for item in result.groups if item.relation.value == "MIRRORED_COPY")
    created = SyncGroupService(catalog).create_from_analysis(
        run_id=result.run_id,
        group_id=candidate.group_id,
        name="api",
        authority_skill_id="codex-api",
        member_skill_ids=["claude-api"],
    )
    removed = runner.invoke(app, ["groups", "remove", created.group_id, "--yes"])
    assert removed.exit_code == 0
    assert catalog.get_current_skill("codex-api") is not None


def test_groups_create_cancel_is_read_only(tmp_path, monkeypatch) -> None:
    state, catalog = _configured(tmp_path)
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    result = runner.invoke(app, ["groups", "create"], input="n\n")
    assert result.exit_code == 0
    assert "已取消" in result.stdout
    from skillcheck.governance.repository import GovernanceRepository

    assert GovernanceRepository(catalog).list_sync_groups() == []
