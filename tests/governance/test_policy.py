from __future__ import annotations

from datetime import UTC, datetime

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config.models import AppConfig
from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.models import Relation
from skillcheck.governance.policy import GovernancePolicy


def _snapshot(skill_id: str, content_hash: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}",
        skill_id=skill_id,
        root_id="root-1",
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        description="A deterministic API validation skill.",
        body="Validate API schemas and report compatible request fields.",
        content_hash=content_hash,
        indexed_at=datetime(2026, 9, 27, tzinfo=UTC),
    )


def test_policy_carries_configured_thresholds_and_embedding_signature(tmp_path) -> None:
    config = AppConfig.default(home=tmp_path / "home")
    config.thresholds.overlap_similarity = 0.70
    config.thresholds.top_k = 2

    policy = GovernancePolicy.from_config(config, project_path=tmp_path)

    assert policy.thresholds.overlap_similarity == 0.70
    assert policy.thresholds.top_k == 2
    assert policy.project_path == tmp_path
    assert policy.embedding_signature == "hash:hash-v1:2:d256:lexical_hash:section-1:feature-2"


def test_analyzer_uses_configured_overlap_threshold(tmp_path) -> None:
    config = AppConfig.default(home=tmp_path / "home")
    config.catalog.database_path = tmp_path / "catalog.db"
    config.catalog.initialized = True
    config.thresholds.overlap_similarity = 0.50
    policy = GovernancePolicy.from_config(config, project_path=tmp_path)

    database = CatalogDatabase(config.catalog.database_path)
    database.initialize()
    repository = CatalogRepository(database)
    repository.upsert_root(
        LibraryRoot(
            root_id="root-1",
            path=tmp_path / "skills",
            provider="codex",
            scope=RootScope.PROJECT,
            project_path=tmp_path,
        )
    )
    repository.upsert_snapshot(_snapshot("skill-a", "sha256:a"))
    repository.upsert_snapshot(_snapshot("skill-b", "sha256:b"))
    repository.save_vector(
        "snapshot-skill-a", policy.embedding_signature, "sha256:a", [1.0, 0.0]
    )
    repository.save_vector(
        "snapshot-skill-b", policy.embedding_signature, "sha256:b", [0.8, 0.6]
    )

    result = GovernanceAnalyzer(repository, policy=policy).analyze_library()

    assert any(group.relation is Relation.HIGH_OVERLAP_CANDIDATE for group in result.groups)
