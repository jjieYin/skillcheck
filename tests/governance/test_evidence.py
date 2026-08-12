from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.models import AppConfig
from skillcheck.governance import GovernanceAnalyzer, Relation, SyncGroupService
from skillcheck.mcp.runtime import McpRuntime


class PendingRuntime:
    def __init__(self, pending_path: Path) -> None:
        self.pending_path = pending_path
        self.before_query_calls = 0
        self.events: list[str] = []

    def is_stale(self, paths: list[Path]) -> bool:
        return self.pending_path in paths

    def before_query(self) -> None:
        self.before_query_calls += 1
        self.events.append("before_query")

    def pending_paths(self) -> set[Path]:
        return {self.pending_path}


def _snapshot(index: int) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{index}",
        skill_id=f"skill-{index:02d}",
        root_id="root-1",
        relative_path=f"skill-{index:02d}/SKILL.md",
        name=f"Skill {index}",
        description="A description.",
        body='token: top-secret\napi_key = "other-secret"\n' + ("Useful evidence. " * 1_000),
        content_hash="sha256:duplicate",
        indexed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def test_evidence_pages_redacts_body_and_preserves_pending_staleness(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    root = tmp_path / "skills"
    catalog.upsert_root(
        LibraryRoot(root_id="root-1", path=root, provider="codex", scope=RootScope.PROJECT)
    )
    for index in range(21):
        snapshot = _snapshot(index)
        path = root / snapshot.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot.body, encoding="utf-8")
        catalog.upsert_snapshot(snapshot)
    pending = root / "skill-00" / "SKILL.md"
    runtime = PendingRuntime(pending)
    analyzer = GovernanceAnalyzer(catalog, runtime=runtime)
    analyzed = analyzer.analyze_library(limit=100)
    runtime.before_query_calls = 0

    first = analyzer.evidence(analyzed.run_id, analyzed.groups[0].group_id, page=1, include_body=True)
    second = analyzer.evidence(analyzed.run_id, analyzed.groups[0].group_id, page=2, include_body=True)

    assert len(first.members) == 20
    assert len(second.members) == 1
    assert first.page_count == 2
    assert first.stale is True
    assert runtime.before_query_calls == 2
    assert "top-secret" not in first.members[0].body
    assert "other-secret" not in first.members[0].body
    assert "[REDACTED]" in first.members[0].body
    assert len(first.members[0].body) <= 12_000


def test_evidence_syncs_runtime_before_reading_members(tmp_path, monkeypatch) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    root = tmp_path / "skills"
    catalog.upsert_root(
        LibraryRoot(root_id="root-1", path=root, provider="codex", scope=RootScope.PROJECT)
    )
    catalog.upsert_snapshot(_snapshot(1))
    catalog.upsert_snapshot(_snapshot(2))
    runtime = PendingRuntime(root / "none")
    analyzer = GovernanceAnalyzer(catalog, runtime=runtime)
    analyzed = analyzer.analyze_library(limit=20)
    runtime.events.clear()
    original = analyzer.repository.evidence_members

    def recording_members(*args):
        runtime.events.append("evidence_members")
        return original(*args)

    monkeypatch.setattr(analyzer.repository, "evidence_members", recording_members)

    analyzer.evidence(analyzed.run_id, analyzed.groups[0].group_id)

    assert runtime.events[:2] == ["before_query", "evidence_members"]


def test_evidence_stays_stale_when_real_runtime_consumes_pending_paths(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    root = tmp_path / "skills"
    catalog.upsert_root(
        LibraryRoot(root_id="root-1", path=root, provider="codex", scope=RootScope.PROJECT)
    )
    for index in range(2):
        snapshot = _snapshot(index)
        path = root / snapshot.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot.body, encoding="utf-8")
        catalog.upsert_snapshot(snapshot)
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.database_path = database.path
    config.catalog.initialized = True
    runtime = McpRuntime(config, repository=catalog, project_path=tmp_path)
    analyzer = GovernanceAnalyzer(catalog, runtime=runtime)
    analyzed = analyzer.analyze_library(limit=20)
    pending = root / "skill-00" / "SKILL.md"
    runtime._on_changes({pending})

    evidence = analyzer.evidence(analyzed.run_id, analyzed.groups[0].group_id)

    assert evidence.stale is True
    assert runtime.pending_paths() == set()


def test_evidence_rejects_a_group_from_another_run(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    catalog.upsert_root(
        LibraryRoot(root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT)
    )
    catalog.upsert_snapshot(_snapshot(1))
    catalog.upsert_snapshot(_snapshot(2))
    analyzer = GovernanceAnalyzer(catalog)
    first = analyzer.analyze_library(limit=20)
    catalog.upsert_snapshot(_snapshot(3).model_copy(update={"content_hash": "sha256:other"}))
    catalog.upsert_snapshot(_snapshot(4).model_copy(update={"content_hash": "sha256:other"}))
    second = analyzer.analyze_library(limit=20)
    first_group_ids = {group.group_id for group in first.groups}
    second_only_group = next(group for group in second.groups if group.group_id not in first_group_ids)

    try:
        analyzer.evidence(first.run_id, second_only_group.group_id)
    except ValueError as error:
        assert "does not belong" in str(error)
    else:
        raise AssertionError("evidence accepted a group belonging to another run")


@pytest.fixture
def analyzer(tmp_path) -> GovernanceAnalyzer:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    roots = {
        "codex-global": LibraryRoot(
            root_id="codex-global", path=tmp_path / "codex-global", provider="codex", scope=RootScope.GLOBAL
        ),
        "claude-global": LibraryRoot(
            root_id="claude-global", path=tmp_path / "claude-global", provider="claude", scope=RootScope.GLOBAL
        ),
        "cursor-project": LibraryRoot(
            root_id="cursor-project", path=tmp_path / "cursor-project", provider="cursor", scope=RootScope.PROJECT,
            project_path=tmp_path / "project",
        ),
    }
    for root in roots.values():
        catalog.upsert_root(root)

    def add(skill_id: str, root_id: str, content_hash: str, *, snapshot_suffix: str = "") -> None:
        catalog.upsert_snapshot(
            SkillSnapshot(
                snapshot_id=f"snapshot-{skill_id}{snapshot_suffix}", skill_id=skill_id, root_id=root_id,
                relative_path=f"{skill_id}/SKILL.md", name=skill_id,
                description="A skill used to verify reporting semantics.",
                body="Useful local governance instructions.", content_hash=content_hash,
                indexed_at=datetime(2026, 8, 12, tzinfo=UTC),
            )
        )

    add("duplicate-a", "codex-global", "sha256:duplicate")
    add("duplicate-b", "codex-global", "sha256:duplicate")
    add("codex-mirror", "codex-global", "sha256:mirror-one")
    add("claude-mirror", "claude-global", "sha256:mirror-one")
    add("codex-project-mirror", "codex-global", "sha256:mirror-two")
    add("cursor-mirror", "cursor-project", "sha256:mirror-two")
    add("sync-authority", "codex-global", "sha256:sync-authority")
    add("sync-mirror", "claude-global", "sha256:sync-mirror")
    add("second-authority", "codex-global", "sha256:second-authority")
    add("second-mirror", "cursor-project", "sha256:second-mirror")

    sync = SyncGroupService(catalog)
    sync.create("first", "sync-authority", ["sync-mirror"], "baseline")
    sync.create("second", "second-authority", ["second-mirror"], "baseline")
    add(
        "sync-authority", "codex-global", "sha256:sync-authority-changed", snapshot_suffix="-changed"
    )
    return GovernanceAnalyzer(catalog)


def test_analysis_counts_mirrors_separately_from_duplicates(analyzer) -> None:
    result = analyzer.analyze_library(limit=None)

    assert result.summary.exact_duplicates == 1
    assert result.summary.mirrored_copy_groups == 2
    assert result.summary.sync_groups_drifted == 1


def test_mirror_evidence_includes_agent_scope_and_snapshot(analyzer) -> None:
    result = analyzer.analyze_library(limit=None)
    mirror = next(group for group in result.groups if group.relation is Relation.MIRRORED_COPY)
    evidence = analyzer.evidence(result.run_id, mirror.group_id, include_body=False)

    assert evidence.members[0].provider == "codex"
    assert evidence.members[0].scope == "global"
    assert evidence.members[0].snapshot_id
    assert evidence.members[0].root_path
