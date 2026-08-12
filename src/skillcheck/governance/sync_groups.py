from __future__ import annotations

from uuid import uuid4

from skillcheck.catalog.models import SkillSnapshot, SkillStatus
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance.models import (
    SyncGroup,
    SyncGroupMember,
    SyncGroupStatus,
    SyncMemberRole,
    SyncPolicy,
)
from skillcheck.governance.repository import GovernanceRepository


def calculate_status(
    group: SyncGroup, current: dict[str, SkillSnapshot | None]
) -> SyncGroupStatus:
    """Classify a group from its immutable baseline and current snapshots."""
    authority = current.get(group.authority_skill_id)
    if authority is None or authority.status is SkillStatus.MISSING:
        return SyncGroupStatus.BROKEN
    if any(item is None or item.status is SkillStatus.MISSING for item in current.values()):
        return SyncGroupStatus.BROKEN
    if any(item is None or item.status is SkillStatus.INVALID for item in current.values()):
        return SyncGroupStatus.INVALID_MEMBER
    if all(item.content_hash == authority.content_hash for item in current.values() if item):
        return SyncGroupStatus.IN_SYNC
    baseline = {member.skill_id: member.baseline_content_hash for member in group.members}
    authority_changed = authority.content_hash != baseline[group.authority_skill_id]
    mirror_changed = any(
        current[member.skill_id].content_hash != member.baseline_content_hash
        for member in group.members
        if member.role is SyncMemberRole.MIRROR and current.get(member.skill_id)
    )
    return SyncGroupStatus.DIVERGED if mirror_changed else (
        SyncGroupStatus.DRIFTED if authority_changed else SyncGroupStatus.DIVERGED
    )


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
        policy: SyncPolicy = SyncPolicy.MONITOR_ONLY,
    ) -> SyncGroup:
        if policy is not SyncPolicy.MONITOR_ONLY:
            raise ValueError("sync group policy must be monitor_only")
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
            policy=policy,
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

    def create_from_analysis(
        self,
        *,
        run_id: str,
        group_id: str,
        name: str,
        authority_skill_id: str,
        member_skill_ids: list[str],
    ) -> SyncGroup:
        """Persist exactly the current immutable baseline from an analysis run."""
        return self.repository.create_sync_group_from_analysis(
            run_id=run_id,
            group_id=group_id,
            name=name,
            authority_skill_id=authority_skill_id,
            member_skill_ids=member_skill_ids,
        )

    def remove(self, group_id: str) -> None:
        self.repository.delete_sync_group(group_id)

    def get(self, group_id: str) -> SyncGroup | None:
        group = self.repository.get_sync_group(group_id)
        return self._refresh_status(group) if group is not None else None

    def list(self) -> list[SyncGroup]:
        return [self._refresh_status(group) for group in self.repository.list_sync_groups()]

    def _refresh_status(self, group: SyncGroup) -> SyncGroup:
        current = self.repository.catalog.get_current_skills(member.skill_id for member in group.members)
        status = calculate_status(group, current)
        self.repository.update_sync_group_status(group.group_id, status)
        return group.model_copy(update={"status": status})
