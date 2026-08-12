from __future__ import annotations

from uuid import uuid4

from skillcheck.catalog.models import SkillStatus
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance.models import (
    SyncGroup,
    SyncGroupMember,
    SyncGroupStatus,
    SyncMemberRole,
    SyncPolicy,
)
from skillcheck.governance.repository import GovernanceRepository


class SyncGroupService:
    """Create and remove bounded, monitor-only synchronization groups."""

    def __init__(self, repository: CatalogRepository | GovernanceRepository) -> None:
        self.repository = (
            repository if isinstance(repository, GovernanceRepository) else GovernanceRepository(repository)
        )

    def create(
        self,
        name: str,
        authority_skill_id: str,
        member_skill_ids: list[str],
        baseline_revision: str,
    ) -> SyncGroup:
        skill_ids = [authority_skill_id, *member_skill_ids]
        if len(skill_ids) < 2:
            raise ValueError("sync group must have at least two members")
        if len(set(skill_ids)) != len(skill_ids):
            raise ValueError("sync group members must be unique")
        snapshots = []
        for skill_id in skill_ids:
            snapshot = self.repository.catalog.get_current_skill(skill_id)
            if snapshot is None or snapshot.status is not SkillStatus.ACTIVE:
                raise ValueError(f"skill is not active: {skill_id}")
            snapshots.append(snapshot)
        group = SyncGroup(
            group_id=f"sync-{uuid4().hex}",
            name=name,
            authority_skill_id=authority_skill_id,
            policy=SyncPolicy.MONITOR_ONLY,
            baseline_revision=baseline_revision,
            status=SyncGroupStatus.IN_SYNC,
            members=[
                SyncGroupMember(
                    skill_id=snapshot.skill_id,
                    role=(
                        SyncMemberRole.AUTHORITY
                        if snapshot.skill_id == authority_skill_id
                        else SyncMemberRole.MIRROR
                    ),
                    baseline_snapshot_id=snapshot.snapshot_id,
                    baseline_content_hash=snapshot.content_hash,
                )
                for snapshot in snapshots
            ],
        )
        self.repository.insert_sync_group(group)
        return group

    def remove(self, group_id: str) -> None:
        self.repository.delete_sync_group(group_id)
