from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import GovernanceAnalyzer
from skillcheck.governance.reviews import ReviewService
from skillcheck.models.audit import AuditGroup, LibraryAuditReport
from skillcheck.models.governance import GovernanceDecision, GroupDecision
from skillcheck.reports.writer import ReportWriter


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

    with catalog.database.connect() as connection:
        hashes = {
            row["format"]: row["content_hash"]
            for row in connection.execute("SELECT format, content_hash FROM reports").fetchall()
        }
    assert hashes["json"] == "sha256:" + hashlib.sha256(saved.json_path.read_bytes()).hexdigest()


def test_generated_report_includes_local_deterministic_findings(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    catalog.upsert_root(
        LibraryRoot(root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT)
    )
    for skill_id in ("skill-a", "skill-b"):
        catalog.upsert_snapshot(
            SkillSnapshot(
                snapshot_id=f"snapshot-{skill_id}",
                skill_id=skill_id,
                root_id="root-1",
                relative_path=f"{skill_id}/SKILL.md",
                name=skill_id,
                description="",
                body="short",
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
                confidence=0.5,
                reason="Keep for manual review.",
            )
        ],
    )

    payload = json.loads(saved.json_path.read_text(encoding="utf-8"))
    assert payload["local_findings"]
    assert any(item["rule_id"] == "FMT002" for item in payload["local_findings"])


def test_local_audit_reports_mirrors_separately_and_only_recommends_monitoring(tmp_path) -> None:
    report = LibraryAuditReport(
        report_id="audit-mirrors",
        scope="local catalog",
        installation_count=4,
        unique_skill_count=3,
        exact_duplicates=1,
        mirrored_copy_groups=2,
        sync_groups_total=2,
        sync_groups_drifted=1,
        groups=[
            AuditGroup(
                group_id="mirror-group",
                relation="MIRRORED_COPY",
                member_skill_ids=["codex-skill", "claude-skill"],
                confidence="local-rule",
                recommendations=["Delete the duplicate."],
            )
        ],
    )

    paths = ReportWriter(tmp_path).write(report)
    markdown = paths.markdown.read_text(encoding="utf-8")
    payload = json.loads(paths.json.read_text(encoding="utf-8"))

    assert "真正冗余：1 组" in markdown
    assert "跨 Agent 镜像副本：2 组（不计入冗余）" in markdown
    assert "同步组：2 个" in markdown
    assert "存在版本漂移：1 个" in markdown
    assert payload["exact_duplicates"] == 1
    assert payload["mirrored_copy_groups"] == 2
    assert payload["groups"][0]["recommendations"] == ["合理跨作用域分发；可选择建立只监测同步组"]
