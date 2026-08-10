from __future__ import annotations

import json
from datetime import UTC, datetime

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import GovernanceAnalyzer
from skillcheck.governance.reviews import ReviewService
from skillcheck.models.governance import GovernanceDecision, GroupDecision


def test_generated_report_has_five_sections_and_hides_skill_bodies(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    skills_path = tmp_path / "skills"
    catalog.upsert_root(
        LibraryRoot(root_id="root-1", path=skills_path, provider="codex", scope=RootScope.PROJECT)
    )
    for skill_id in ("skill-a", "skill-b"):
        catalog.upsert_snapshot(
            SkillSnapshot(
                snapshot_id=f"snapshot-{skill_id}",
                skill_id=skill_id,
                root_id="root-1",
                relative_path=f"{skill_id}/SKILL.md",
                name=skill_id,
                description="Secret-safe report check.",
                body="token: must-not-appear-in-report",
                content_hash="sha256:duplicate",
                indexed_at=datetime(2026, 8, 10, tzinfo=UTC),
            )
        )
    result = GovernanceAnalyzer(catalog).analyze_library(limit=20)

    saved = ReviewService(catalog, tmp_path / "reports").save(
        result.run_id,
        [
            GroupDecision(
                group_id=result.groups[0].group_id,
                decision=GovernanceDecision.MANUAL_REVIEW,
                confidence=0.7,
                reason="Review the boundaries before changing user-owned files.",
            )
        ],
    )

    markdown = saved.markdown_path.read_text(encoding="utf-8")
    payload = json.loads(saved.json_path.read_text(encoding="utf-8"))
    assert [line for line in markdown.splitlines() if line.startswith("## ")] == [
        "## 本地确定性问题",
        "## 相似候选与证据",
        "## Agent 语义判断",
        "## 建议的人工操作",
        "## 安全边界",
    ]
    assert payload["run_id"] == result.run_id
    assert payload["revision"] == result.revision
    assert "snapshot_ids" in payload
    assert "local_findings" in payload
    assert "must-not-appear-in-report" not in markdown
    assert "must-not-appear-in-report" not in saved.json_path.read_text(encoding="utf-8")
