from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config
from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.sync_groups import SyncGroupService

runner = CliRunner()


def _write_skill(root: Path, body: str, name: str = "api-review") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(
        "---\nname: api-review\ndescription: Review API contracts\n---\n\n" + body,
        encoding="utf-8",
    )
    return path


def test_v5_mirror_and_sync_group_journey(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state"
    codex_root = tmp_path / "codex-skills"
    claude_root = tmp_path / "claude-skills"
    codex_skill = _write_skill(codex_root, "Review request and response fields.", "codex-api")
    claude_skill = _write_skill(claude_root, "Review request and response fields.", "claude-api")
    monkeypatch.setenv("SKILLCHECK_HOME", str(state))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    initialized = runner.invoke(app, ["init", str(codex_root), str(claude_root), "--yes"])
    assert initialized.exit_code == 0
    status = json.loads(runner.invoke(app, ["status", "--json"]).stdout)
    assert status["skill_count"] >= 2

    config = load_config(create=False)
    catalog = CatalogRepository(CatalogDatabase(config.catalog.database_path))
    analysis = GovernanceAnalyzer(catalog).analyze_library(trigger_source="explicit_user")
    mirror = next(group for group in analysis.groups if group.relation.value == "MIRRORED_COPY")
    authority = next(
        skill.skill_id
        for skill in catalog.list_current_skills()
        if skill.relative_path == "codex-api/SKILL.md" and skill.skill_id in mirror.member_skill_ids
    )
    members = [skill_id for skill_id in mirror.member_skill_ids if skill_id != authority]
    created = SyncGroupService(catalog).create_from_analysis(
        run_id=analysis.run_id,
        group_id=mirror.group_id,
        name="api-review-mirror",
        authority_skill_id=authority,
        member_skill_ids=members,
    )
    assert created.status.value == "IN_SYNC"

    codex_skill.write_text(codex_skill.read_text(encoding="utf-8") + "\nExtra authority guidance.\n", encoding="utf-8")
    assert runner.invoke(app, ["sync"]).exit_code == 0
    listed = runner.invoke(app, ["groups", "list", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)[0]["status"] == "DRIFTED"
    assert "Extra authority guidance" in codex_skill.read_text(encoding="utf-8")
    assert "Extra authority guidance" not in claude_skill.read_text(encoding="utf-8")
