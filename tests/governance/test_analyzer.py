from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.models import AppConfig
from skillcheck.governance import AnalyzeMode, GovernanceAnalyzer, Relation
from skillcheck.governance.policy import GovernancePolicy


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

    result = analyzer.analyze_library(scope="all")

    assert result.mode is AnalyzeMode.LIBRARY
    assert result.run_id.startswith("run-")
    assert result.summary.exact_duplicates == 1
    assert result.groups[0].relation is Relation.EXACT_DUPLICATE
    assert result.groups[0].member_skill_ids == ["skill-a", "skill-b"]
    assert result.next_tool == "skillcheck_evidence"


def test_library_analyze_records_trigger_source(
    analyzer: GovernanceAnalyzer, repository: CatalogRepository
) -> None:
    result = analyzer.analyze_library(trigger_source="explicit_user")

    assert repository.analysis_parameters(result.run_id)["trigger_source"] == "explicit_user"


def test_library_analyze_classifies_cross_agent_hash_matches_as_mirrors(
    analyzer: GovernanceAnalyzer, repository: CatalogRepository, tmp_path
) -> None:
    repository.upsert_root(
        LibraryRoot(
            root_id="root-2", path=tmp_path / "claude-skills", provider="claude", scope=RootScope.PROJECT
        )
    )
    repository.upsert_snapshot(_snapshot("codex-copy", "sha256:mirror"))
    repository.upsert_snapshot(
        _snapshot("claude-copy", "sha256:mirror").model_copy(update={"root_id": "root-2"})
    )

    result = analyzer.analyze_library(scope="all")

    assert [(group.relation, group.member_skill_ids) for group in result.groups] == [
        (Relation.MIRRORED_COPY, ["claude-copy", "codex-copy"])
    ]


def test_library_analyze_sorts_relation_then_similarity_then_group_id(
    analyzer: GovernanceAnalyzer, repository: CatalogRepository
) -> None:
    repository.upsert_snapshot(_snapshot("skill-a", "sha256:duplicate"))
    repository.upsert_snapshot(_snapshot("skill-b", "sha256:duplicate"))
    repository.upsert_snapshot(_snapshot("skill-c", "sha256:other"))
    repository.upsert_snapshot(_snapshot("skill-d", "sha256:other-2"))
    snapshots = {item.skill_id: item for item in repository.list_current_skills()}
    model = analyzer.policy.embedding_signature
    repository.save_vector(snapshots["skill-c"].snapshot_id, model, "sha256:other", [1, 0])
    repository.save_vector(snapshots["skill-d"].snapshot_id, model, "sha256:other-2", [1, 0])

    result = analyzer.analyze_library(scope="all")

    assert [group.relation for group in result.groups] == [
        Relation.EXACT_DUPLICATE,
        Relation.HIGH_OVERLAP_CANDIDATE,
    ]


def test_source_analysis_binds_revision_to_source_hash(analyzer: GovernanceAnalyzer, tmp_path) -> None:
    source = tmp_path / "staged-source"
    skill = source / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: Example\n---\nUseful steps.\n", encoding="utf-8")

    result = analyzer.analyze_source(source)

    assert result.mode is AnalyzeMode.SOURCE
    assert result.revision.startswith("sha256:")
    assert result.summary.skills_considered == 1


def test_source_analysis_finds_overlap_with_catalog(analyzer: GovernanceAnalyzer, repository, tmp_path) -> None:
    repository.upsert_snapshot(
        _snapshot(
            "catalog-skill",
            "sha256:catalog",
            body="Validate API schemas and report compatible request fields.",
        ).model_copy(update={"description": "Validate API schemas."})
    )
    source = tmp_path / "staged-source"
    skill = source / "incoming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: Incoming\ndescription: Validate API schemas.\n---\n"
        "Validate API schemas and report compatible request fields.\n",
        encoding="utf-8",
    )

    result = analyzer.analyze_source(source)

    overlap = next(group for group in result.groups if group.relation is Relation.HIGH_OVERLAP_CANDIDATE)
    assert "catalog-skill" in overlap.member_skill_ids
    assert len(overlap.member_skill_ids) == 2


def test_source_analysis_considers_all_incoming_and_catalog_skills(
    analyzer: GovernanceAnalyzer, repository, tmp_path
) -> None:
    for index in range(20):
        repository.upsert_snapshot(
            _snapshot(
                f"catalog-{index:02d}",
                f"sha256:catalog-{index}",
                body=f"Unrelated catalog skill {index}.",
            ).model_copy(update={"description": "Unrelated catalog skill."})
        )
    repository.upsert_snapshot(
        _snapshot(
            "catalog-match",
            "sha256:catalog-match",
            body="Validate API schemas and report compatible request fields.",
        ).model_copy(update={"description": "Validate API schemas."})
    )
    source = tmp_path / "staged-source"
    skill = source / "incoming"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: Incoming\ndescription: Validate API schemas.\n---\n"
        "Validate API schemas and report compatible request fields.\n",
        encoding="utf-8",
    )

    result = analyzer.analyze_source(source)

    assert result.summary.skills_considered == 22
    assert any("catalog-match" in group.member_skill_ids for group in result.groups)


def test_analyze_dispatches_library_mode(analyzer: GovernanceAnalyzer) -> None:
    result = analyzer.analyze(AnalyzeMode.LIBRARY)

    assert result.mode is AnalyzeMode.LIBRARY


def test_analyze_rejects_an_unknown_scope(analyzer: GovernanceAnalyzer) -> None:
    with pytest.raises(ValueError, match="scope"):
        analyzer.analyze_library(scope="unknown")


def test_analyze_never_calls_an_agent_process(analyzer: GovernanceAnalyzer, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("governance analysis must not start an Agent subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)

    analyzer.analyze_library(scope="all")


def test_default_library_analysis_considers_every_indexed_skill(
    analyzer: GovernanceAnalyzer, repository: CatalogRepository
) -> None:
    for index in range(168):
        body = "duplicate tail" if index in {160, 167} else f"unique {index}"
        content_hash = "sha256:duplicate-tail" if index in {160, 167} else f"sha256:{index}"
        repository.upsert_snapshot(_snapshot(f"skill-{index:03d}", content_hash, body=body))

    result = analyzer.analyze_library()

    assert result.summary.skills_considered == 168
    assert any(
        group.relation is Relation.EXACT_DUPLICATE
        and set(group.member_skill_ids) == {"skill-160", "skill-167"}
        for group in result.groups
    )


def test_library_analysis_applies_scope_to_catalog_roots(repository: CatalogRepository, tmp_path) -> None:
    current_project = (tmp_path / "current").resolve()
    repository.upsert_root(
        LibraryRoot(root_id="global-root", path=tmp_path / "global", provider="codex", scope=RootScope.GLOBAL)
    )
    repository.upsert_root(
        LibraryRoot(
            root_id="project-root",
            path=tmp_path / "project",
            provider="codex",
            scope=RootScope.PROJECT,
            project_path=current_project,
        )
    )
    repository.upsert_root(
        LibraryRoot(
            root_id="other-project-root",
            path=tmp_path / "other",
            provider="codex",
            scope=RootScope.PROJECT,
            project_path=tmp_path / "other-project",
        )
    )
    repository.upsert_snapshot(_snapshot("global-skill", "sha256:global").model_copy(update={"root_id": "global-root"}))
    repository.upsert_snapshot(_snapshot("project-skill", "sha256:project").model_copy(update={"root_id": "project-root"}))
    repository.upsert_snapshot(_snapshot("other-skill", "sha256:other").model_copy(update={"root_id": "other-project-root"}))
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.database_path = repository.database.path
    policy = GovernancePolicy.from_config(config, project_path=current_project)

    result = GovernanceAnalyzer(repository, policy=policy).analyze_library(scope="project")

    assert result.summary.skills_considered == 1


def test_analyzer_reads_only_the_active_embedding_signature(repository: CatalogRepository, tmp_path) -> None:
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.database_path = repository.database.path
    policy = GovernancePolicy.from_config(config, project_path=tmp_path)
    snapshot = _snapshot("skill-a", "sha256:a")
    repository.upsert_snapshot(snapshot)
    repository.save_vector(snapshot.snapshot_id, "old-model", snapshot.content_hash, [1.0, 0.0])
    repository.save_vector(
        snapshot.snapshot_id,
        policy.embedding_signature,
        snapshot.content_hash,
        [0.0, 1.0],
    )

    analyzer = GovernanceAnalyzer(repository, policy=policy)
    vectors = analyzer._vectors_for([snapshot])

    assert list(vectors["skill-a"]) == [0.0, 1.0]


def test_analyzer_keeps_skill_findings_separate_from_pair_relations(
    repository: CatalogRepository,
) -> None:
    unsafe = _snapshot(
        "unsafe",
        "sha256:unsafe",
        body="A hardcoded token is sk-abcdefghijklmnop.",
    )
    normal = _snapshot("normal", "sha256:normal", body="A complete normal skill body.")
    repository.upsert_snapshot(unsafe)
    repository.upsert_snapshot(normal)
    model = GovernancePolicy.default().embedding_signature
    repository.save_vector(unsafe.snapshot_id, model, unsafe.content_hash, [1.0, 0.0])
    repository.save_vector(normal.snapshot_id, model, normal.content_hash, [0.99, 0.01])

    result = GovernanceAnalyzer(repository).analyze_library()

    assert any(item.skill_id == "unsafe" and item.finding.rule_id == "SEC002" for item in result.skill_findings)
    assert all(item.skill_id == "unsafe" for item in result.skill_findings if item.finding.rule_id == "SEC002")
    assert all(group.relation not in {Relation.SECURITY_ISSUE, Relation.QUALITY_ISSUE} for group in result.groups)
    assert result.summary.security_issues >= 1
    parameters = repository.analysis_parameters(result.run_id)
    assert parameters["scope"] == "all"
    assert parameters["embedding_signature"] == GovernancePolicy.default().embedding_signature
    assert parameters["thresholds"]["top_k"] == GovernancePolicy.default().thresholds.top_k
    assert any(item["skill_id"] == "unsafe" for item in parameters["skill_findings"])
