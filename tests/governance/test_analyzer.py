from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import AnalyzeMode, GovernanceAnalyzer, Relation


def _snapshot(skill_id: str, content_hash: str, *, body: str = "A complete skill body.") -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}",
        skill_id=skill_id,
        root_id="root-1",
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        body=body,
        content_hash=content_hash,
        indexed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


@pytest.fixture
def repository(tmp_path) -> CatalogRepository:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    repository.upsert_root(
        LibraryRoot(
            root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT
        )
    )
    return repository


@pytest.fixture
def analyzer(repository: CatalogRepository) -> GovernanceAnalyzer:
    return GovernanceAnalyzer(repository)


def test_library_analyze_groups_exact_duplicates_and_persists_run(
    analyzer: GovernanceAnalyzer, repository: CatalogRepository
) -> None:
    repository.upsert_snapshot(_snapshot("skill-a", "sha256:duplicate"))
    repository.upsert_snapshot(_snapshot("skill-b", "sha256:duplicate"))

    result = analyzer.analyze_library(scope="all", limit=20)

    assert result.mode is AnalyzeMode.LIBRARY
    assert result.run_id.startswith("run-")
    assert result.summary.exact_duplicates == 1
    assert result.groups[0].relation is Relation.EXACT_DUPLICATE
    assert result.groups[0].member_skill_ids == ["skill-a", "skill-b"]
    assert result.next_tool == "skillcheck_evidence"


def test_library_analyze_sorts_relation_then_similarity_then_group_id(
    analyzer: GovernanceAnalyzer, repository: CatalogRepository
) -> None:
    repository.upsert_snapshot(_snapshot("skill-a", "sha256:duplicate"))
    repository.upsert_snapshot(_snapshot("skill-b", "sha256:duplicate"))
    repository.upsert_snapshot(_snapshot("skill-c", "sha256:other"))
    repository.upsert_snapshot(_snapshot("skill-d", "sha256:other-2"))
    snapshots = {item.skill_id: item for item in repository.list_current_skills()}
    repository.save_vector(snapshots["skill-c"].snapshot_id, "local-v1", "sha256:other", [1, 0])
    repository.save_vector(snapshots["skill-d"].snapshot_id, "local-v1", "sha256:other-2", [1, 0])

    result = analyzer.analyze_library(scope="all", limit=20)

    assert [group.relation for group in result.groups] == [
        Relation.EXACT_DUPLICATE,
        Relation.HIGH_OVERLAP_CANDIDATE,
    ]


def test_source_analysis_binds_revision_to_source_hash(analyzer: GovernanceAnalyzer, tmp_path) -> None:
    source = tmp_path / "staged-source"
    skill = source / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: Example\n---\nUseful steps.\n", encoding="utf-8")

    result = analyzer.analyze_source(source, limit=20)

    assert result.mode is AnalyzeMode.SOURCE
    assert result.revision.startswith("sha256:")
    assert result.summary.skills_considered == 1


def test_analyze_dispatches_library_mode(analyzer: GovernanceAnalyzer) -> None:
    result = analyzer.analyze(AnalyzeMode.LIBRARY, limit=20)

    assert result.mode is AnalyzeMode.LIBRARY


@pytest.mark.parametrize("limit", [0, 101])
def test_analyze_rejects_an_unbounded_limit(analyzer: GovernanceAnalyzer, limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        analyzer.analyze_library(scope="all", limit=limit)


def test_analyze_never_calls_an_agent_process(analyzer: GovernanceAnalyzer, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("governance analysis must not start an Agent subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)

    analyzer.analyze_library(scope="all", limit=20)
