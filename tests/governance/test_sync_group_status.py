from __future__ import annotations

from datetime import UTC, datetime

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot, SkillStatus
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import SyncGroupService, SyncGroupStatus


def _snapshot(
    skill_id: str,
    *,
    content_hash: str = "sha256:baseline",
    status: SkillStatus = SkillStatus.ACTIVE,
    revision: str = "baseline",
) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=f"snapshot-{skill_id}-{revision}",
        skill_id=skill_id,
        root_id="root-1",
        relative_path=f"{skill_id}/SKILL.md",
        name=skill_id,
        content_hash=content_hash,
        status=status,
        indexed_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


@pytest.fixture
def sync_group_scenario(tmp_path):
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    catalog.upsert_root(
        LibraryRoot(
            root_id="root-1", path=tmp_path / "skills", provider="codex", scope=RootScope.PROJECT
        )
    )
    for skill_id in ("authority", "mirror"):
        catalog.upsert_snapshot(_snapshot(skill_id))
    service = SyncGroupService(catalog)
    group = service.create("shared-api", "authority", ["mirror"], "sync-1")

    def scenario(name: str):
        if name == "authority_changed_mirrors_unchanged":
            catalog.upsert_snapshot(
                _snapshot("authority", content_hash="sha256:authority-change", revision="changed")
            )
        elif name == "mirror_changed_independently":
            catalog.upsert_snapshot(
                _snapshot("mirror", content_hash="sha256:mirror-change", revision="changed")
            )
        elif name == "authority_missing":
            catalog.mark_missing("authority")
        elif name == "member_invalid":
            catalog.upsert_snapshot(
                _snapshot("mirror", status=SkillStatus.INVALID, revision="invalid")
            )
        elif name != "all_equal":
            raise ValueError(f"unknown scenario: {name}")
        refreshed = service.get(group.group_id)
        assert refreshed is not None
        assert service.list() == [refreshed]
        return refreshed

    return scenario


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("all_equal", SyncGroupStatus.IN_SYNC),
        ("authority_changed_mirrors_unchanged", SyncGroupStatus.DRIFTED),
        ("mirror_changed_independently", SyncGroupStatus.DIVERGED),
        ("authority_missing", SyncGroupStatus.BROKEN),
        ("member_invalid", SyncGroupStatus.INVALID_MEMBER),
    ],
)
def test_sync_group_status(sync_group_scenario, scenario, expected) -> None:
    assert sync_group_scenario(scenario).status is expected


def test_get_and_list_refresh_status_without_changing_member_baselines(sync_group_scenario) -> None:
    group = sync_group_scenario("authority_changed_mirrors_unchanged")

    assert group.status is SyncGroupStatus.DRIFTED
    assert [member.baseline_content_hash for member in group.members] == [
        "sha256:baseline",
        "sha256:baseline",
    ]
