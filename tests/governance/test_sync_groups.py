from __future__ import annotations

from datetime import UTC, datetime

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import SyncGroupService, SyncMemberRole, SyncPolicy


def _snapshot(skill_id: str) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}",
        skill_id=skill_id,
        root_id="root-1",
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        content_hash=f"sha256:{skill_id}",
        indexed_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


@pytest.fixture
def catalog_with_three_agents(tmp_path) -> CatalogRepository:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    repository.upsert_root(
        LibraryRoot(
            root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT
        )
    )
    for skill_id in ("codex-api", "claude-api", "cursor-api"):
        repository.upsert_snapshot(_snapshot(skill_id))
    return repository


def test_create_sync_group_persists_authority_and_mirrors(catalog_with_three_agents) -> None:
    service = SyncGroupService(catalog_with_three_agents)

    created = service.create(
        name="api-review",
        authority_skill_id="codex-api",
        member_skill_ids=["claude-api", "cursor-api"],
        baseline_revision="sync-1",
    )

    assert created.policy is SyncPolicy.MONITOR_ONLY
    assert [member.role for member in created.members] == [
        SyncMemberRole.AUTHORITY,
        SyncMemberRole.MIRROR,
        SyncMemberRole.MIRROR,
    ]


def test_one_skill_cannot_belong_to_two_sync_groups(catalog_with_three_agents) -> None:
    service = SyncGroupService(catalog_with_three_agents)
    service.create("first", "codex-api", ["claude-api"], "sync-1")

    with pytest.raises(ValueError, match="already belongs"):
        service.create("second", "cursor-api", ["claude-api"], "sync-1")


def test_remove_group_does_not_delete_skills(catalog_with_three_agents) -> None:
    service = SyncGroupService(catalog_with_three_agents)
    group = service.create("api", "codex-api", ["claude-api"], "sync-1")

    service.remove(group.group_id)

    assert catalog_with_three_agents.get_current_skill("codex-api") is not None
