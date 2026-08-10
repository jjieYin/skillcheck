from __future__ import annotations

from datetime import UTC, datetime

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import GovernanceAnalyzer
from skillcheck.governance.reviews import ReviewService, StaleAnalysisError
from skillcheck.models.governance import GovernanceDecision, GroupDecision


def _snapshot(skill_id: str, content_hash: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}-{content_hash.rsplit(':', 1)[-1]}",
        skill_id=skill_id,
        root_id="root-1",
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        description="An API validation skill.",
        body="Validate API request fields.",
        content_hash=content_hash,
        indexed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


@pytest.fixture
def prepared(tmp_path):
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    catalog.upsert_root(
        LibraryRoot(
            root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT
        )
    )
    catalog.upsert_snapshot(_snapshot("skill-a", "sha256:duplicate"))
    catalog.upsert_snapshot(_snapshot("skill-b", "sha256:duplicate"))
    analyzer = GovernanceAnalyzer(catalog)
    result = analyzer.analyze_library(limit=20)
    return catalog, result, tmp_path / "reports"


def _decision(group_id: str, **updates: object) -> GroupDecision:
    values: dict[str, object] = {
        "group_id": group_id,
        "decision": GovernanceDecision.MERGE,
        "canonical_skill": "skill-a",
        "confidence": 0.9,
        "reason": "The two Skills have the same implementation boundary.",
        "recommendations": ["Merge the unique examples before manual cleanup."],
    }
    values.update(updates)
    return GroupDecision(**values)


def test_save_review_persists_structured_decision_and_report(prepared) -> None:
    catalog, result, reports_path = prepared

    saved = ReviewService(catalog, reports_path).save(result.run_id, [_decision(result.groups[0].group_id)])

    assert saved.run_id == result.run_id
    assert saved.revision == result.revision
    assert saved.decisions[0].decision is GovernanceDecision.MERGE
    assert saved.markdown_path.exists()
    assert saved.json_path.exists()
    with catalog.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM agent_reviews").fetchone()[0] == 1


@pytest.mark.parametrize(
    "decisions",
    [
        lambda group_id: [_decision("not-in-run")],
        lambda group_id: [_decision(group_id, canonical_skill="not-a-member")],
        lambda group_id: [_decision(group_id), _decision(group_id, decision=GovernanceDecision.KEEP_BOTH)],
    ],
)
def test_save_review_rejects_invalid_group_canonical_and_duplicates(prepared, decisions) -> None:
    catalog, result, reports_path = prepared
    service = ReviewService(catalog, reports_path)

    with pytest.raises(ValueError):
        service.save(result.run_id, decisions(result.groups[0].group_id))

    with catalog.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM agent_reviews").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reports").fetchone()[0] == 0
    assert not reports_path.exists()


def test_save_review_rejects_when_group_snapshot_is_no_longer_current(prepared) -> None:
    catalog, result, reports_path = prepared
    catalog.upsert_snapshot(_snapshot("skill-a", "sha256:changed"))

    with pytest.raises(StaleAnalysisError):
        ReviewService(catalog, reports_path).save(result.run_id, [_decision(result.groups[0].group_id)])

    with catalog.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM agent_reviews").fetchone()[0] == 0
    assert not reports_path.exists()
