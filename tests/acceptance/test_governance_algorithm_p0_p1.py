from __future__ import annotations

import time
from pathlib import Path

from skillcheck.audit import LibraryAuditor
from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.models import AppConfig
from skillcheck.governance import GovernanceAnalyzer, Relation
from skillcheck.governance.policy import GovernancePolicy
from skillcheck.mcp.runtime import McpRuntime
from skillcheck.mcp.tools import SkillcheckMcpTools
from skillcheck.models.governance import GovernanceDecision
from tests.helpers import skill_record


class _Watcher:
    warning = None
    running = False

    def __init__(self, roots, on_changes, **kwargs) -> None:
        self.on_changes = on_changes

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


def _write_skill(
    root: Path,
    name: str,
    body: str,
    *,
    asset: str | None = None,
    frontmatter_name: str | None = None,
) -> Path:
    skill = root / name
    skill.mkdir(parents=True, exist_ok=True)
    path = skill / "SKILL.md"
    metadata_name = frontmatter_name or name
    path.write_text(
        f"---\nname: {metadata_name}\ndescription: shared governance test\n---\n{body}\n",
        encoding="utf-8",
    )
    if asset is not None:
        (skill / "reference.txt").write_text(asset, encoding="utf-8")
    return path


def test_mcp_runtime_scope_hash_evidence_and_review_boundary(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    global_root = home / ".codex" / "skills"
    project_root = project / ".codex" / "skills"
    other_root = tmp_path / "other" / ".codex" / "skills"
    global_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    other_root.mkdir(parents=True)

    _write_skill(global_root, "global-only", "Global instructions.")
    _write_skill(other_root, "other-only", "Other project instructions.")
    chinese = "检查接口返回字段并报告错误"
    _write_skill(project_root, "zh-a", chinese, asset="one", frontmatter_name="zh-shared")
    _write_skill(project_root, "zh-b", chinese, asset="two", frontmatter_name="zh-shared")
    secret = _write_skill(project_root, "secret-skill", "API_KEY='sk-abcdefghijklmnop'")

    config = AppConfig.default(home=home)
    config.catalog.initialized = True
    config.catalog.database_path = tmp_path / "state" / "index.db"
    config.reports.directory = tmp_path / "state" / "reports"
    config.catalog.roots = [other_root]
    database = CatalogDatabase(config.catalog.database_path)
    database.initialize()
    repository = CatalogRepository(database)
    runtime = McpRuntime(
        config,
        repository,
        home=home,
        project_path=project,
        watcher_factory=_Watcher,
    )
    runtime.start()
    tools = SkillcheckMcpTools(runtime)

    project_result = tools.analyze("library", scope="project")
    project_ids = {
        member
        for group in project_result["groups"]
        for member in group["member_skill_ids"]
    }
    skill_ids = {
        Path(item.relative_path).parent.name: item.skill_id
        for item in repository.list_current_skills()
    }
    assert "other-only" not in {item.name for item in repository.list_current_skills() if item.skill_id in project_ids}
    assert project_result["summary"]["skills_considered"] == 3

    before = secret.read_bytes()
    secret.write_text(secret.read_text(encoding="utf-8") + "\nUpdated.\n", encoding="utf-8")
    runtime._on_changes({secret})
    tools.analyze("library", scope="project")
    current = next(item for item in repository.list_current_skills() if item.name == "secret-skill")
    assert current is not None
    assert repository.has_vector(current.snapshot_id, GovernancePolicy.default().embedding_signature)

    latest = tools.analyze("library", scope="project")
    overlap = next(
        group
        for group in latest["groups"]
        if group["relation"] == Relation.HIGH_OVERLAP_CANDIDATE.value
        and skill_ids["zh-a"] in group["member_skill_ids"]
        and skill_ids["zh-b"] in group["member_skill_ids"]
    )
    evidence = tools.evidence(latest["run_id"], overlap["group_id"], page=0)
    assert evidence["pair_evidence"]
    assert any(
        item["skill_id"] == skill_ids["secret-skill"]
        and item["finding"]["rule_id"] == "SEC002"
        for item in latest["skill_findings"]
    )
    assert all(group["relation"] != Relation.SECURITY_ISSUE.value for group in latest["groups"])

    unchanged_after_analysis = secret.read_bytes()
    tools.save_review(
        latest["run_id"],
        [
            {
                "group_id": overlap["group_id"],
                "decision": GovernanceDecision.MANUAL_REVIEW.value,
                "confidence": 0.5,
                "reason": "Review the Chinese procedure boundary.",
            }
        ],
    )
    assert unchanged_after_analysis != before
    assert secret.read_bytes() == unchanged_after_analysis
    runtime.stop()

    chain_skills = [
        skill_record(
            skill_id=item,
            name=f"name{item}",
            description=f"description{item}",
            body=f"body{item}",
            content_hash=f"package-{item}",
        )
        for item in "abc"
    ]
    chain = LibraryAuditor(top_k=5).audit(
        chain_skills,
        {"a": [1.0, 0.0], "b": [0.99, 0.141067], "c": [0.8, 0.6]},
        findings=[],
    )
    assert not any(
        group.relation == Relation.HIGH_OVERLAP_CANDIDATE.value
        and set(group.member_skill_ids) == {"a", "b", "c"}
        for group in chain.groups
    )


def test_complete_168_skill_analysis_remains_bounded(tmp_path: Path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    root = LibraryRoot(root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.GLOBAL)
    repository.upsert_root(root)
    for index in range(168):
        repository.upsert_snapshot(
            SkillSnapshot(
                snapshot_id=f"snapshot-{index}",
                skill_id=f"skill-{index:03d}",
                root_id=root.root_id,
                relative_path=f"skill-{index:03d}/SKILL.md",
                name=f"skill-{index:03d}",
                description=f"Description {index}",
                body=f"Procedure {index} has bounded local steps.",
                content_hash=f"package-{index}",
                indexed_at="2026-09-28T00:00:00+00:00",
            )
        )

    started = time.perf_counter()
    result = GovernanceAnalyzer(repository).analyze_library(scope="all")
    elapsed = time.perf_counter() - started

    assert result.summary.skills_considered == 168
    assert elapsed < 30
