from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from skillcheck.catalog.models import SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance.models import (
    CandidateGroupSummary,
    SourcePreflight,
    SyncGroup,
    SyncGroupMember,
    SyncGroupStatus,
)
from skillcheck.models.audit import Finding

if TYPE_CHECKING:
    from skillcheck.models.governance import GroupDecision


@dataclass(frozen=True)
class ReviewGroup:
    group_id: str
    relation: str
    similarity: float | None
    member_skill_ids: list[str]
    snapshot_ids: list[str]


@dataclass(frozen=True)
class ReviewContext:
    run_id: str
    revision: str
    groups: list[ReviewGroup]
    local_findings: list[dict[str, object]]
    is_current: bool


@dataclass(frozen=True)
class EvidenceMember:
    """Snapshot evidence plus the catalog root that owns it."""

    snapshot: SkillSnapshot
    provider: str
    scope: str
    project_path: str | None
    root_path: str


class GovernanceRepository:
    """Persist bounded local analysis results in the catalog's v4 tables."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self.catalog = catalog

    def insert_sync_group(self, group: SyncGroup) -> None:
        """Atomically persist a monitor-only group and its immutable member baselines."""
        now = datetime.now(UTC).isoformat()
        with self.catalog.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._insert_sync_group(connection, group, now)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def create_sync_group_from_analysis(
        self,
        *,
        run_id: str,
        group_id: str,
        name: str,
        authority_skill_id: str,
        member_skill_ids: list[str],
    ) -> SyncGroup:
        """Save a mirror group only if its analyzed baseline remains current while writing."""
        from skillcheck.governance.models import SyncMemberRole, SyncPolicy
        from skillcheck.governance.reviews import StaleAnalysisError

        requested = [authority_skill_id, *member_skill_ids]
        stored_group_id = _stored_group_id(run_id, group_id)
        with self.catalog.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                run = connection.execute(
                    "SELECT revision, status FROM analysis_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if run is None:
                    raise ValueError(f"unknown analysis run: {run_id}")
                if run["status"] != "complete":
                    raise ValueError("analysis run is not complete")
                candidate = connection.execute(
                    "SELECT kind FROM candidate_groups WHERE group_id = ? AND run_id = ?",
                    (stored_group_id, run_id),
                ).fetchone()
                if candidate is None:
                    raise ValueError("group does not belong to analysis run")
                if candidate["kind"] != "MIRRORED_COPY":
                    raise ValueError("group must have MIRRORED_COPY relation")
                rows = connection.execute(
                    """
                    SELECT group_members.snapshot_id AS analyzed_snapshot_id,
                           skill_snapshots.skill_id,
                           skill_snapshots.content_hash AS analyzed_content_hash,
                           skills.status AS current_status,
                           skills.current_snapshot_id,
                           current_snapshots.content_hash AS current_content_hash
                    FROM group_members
                    JOIN skill_snapshots ON skill_snapshots.snapshot_id = group_members.snapshot_id
                    LEFT JOIN skills ON skills.skill_id = skill_snapshots.skill_id
                    LEFT JOIN skill_snapshots AS current_snapshots
                      ON current_snapshots.snapshot_id = skills.current_snapshot_id
                    WHERE group_members.group_id = ?
                    ORDER BY skill_snapshots.skill_id
                    """,
                    (stored_group_id,),
                ).fetchall()
                analyzed_ids = [row["skill_id"] for row in rows]
                if len(requested) != len(set(requested)) or set(requested) != set(analyzed_ids):
                    raise ValueError("authority and member_skill_ids must match the analyzed group")
                if authority_skill_id not in analyzed_ids:
                    raise ValueError("authority_skill_id must belong to the analyzed group")
                latest = connection.execute(
                    "SELECT revision FROM sync_events ORDER BY completed_at DESC, event_id DESC LIMIT 1"
                ).fetchone()
                revision_changed = (
                    latest is not None
                    and not str(run["revision"]).startswith("sha256:")
                    and latest["revision"] != run["revision"]
                )
                snapshots_changed = any(
                    row["current_status"] != "active"
                    or row["current_snapshot_id"] is None
                    or row["current_snapshot_id"] != row["analyzed_snapshot_id"]
                    or row["current_content_hash"] != row["analyzed_content_hash"]
                    for row in rows
                )
                if revision_changed or snapshots_changed:
                    raise StaleAnalysisError("analysis snapshots have changed; analyze again before saving")
                group = SyncGroup(
                    group_id=f"sync-{uuid4().hex}",
                    name=name,
                    authority_skill_id=authority_skill_id,
                    policy=SyncPolicy.MONITOR_ONLY,
                    baseline_revision=run["revision"],
                    status=SyncGroupStatus.IN_SYNC,
                    members=[
                        SyncGroupMember(
                            skill_id=row["skill_id"],
                            role=(
                                SyncMemberRole.AUTHORITY
                                if row["skill_id"] == authority_skill_id
                                else SyncMemberRole.MIRROR
                            ),
                            baseline_snapshot_id=row["analyzed_snapshot_id"],
                            baseline_content_hash=row["analyzed_content_hash"],
                        )
                        for row in sorted(
                            rows,
                            key=lambda row: (row["skill_id"] != authority_skill_id, row["skill_id"]),
                        )
                    ],
                )
                self._insert_sync_group(connection, group, datetime.now(UTC).isoformat())
                connection.commit()
                return group
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _insert_sync_group(connection, group: SyncGroup, now: str) -> None:
        for member in group.members:
            skill = connection.execute(
                "SELECT status, current_snapshot_id FROM skills WHERE skill_id = ?",
                (member.skill_id,),
            ).fetchone()
            if skill is None or skill["status"] != "active":
                raise ValueError(f"skill is not active: {member.skill_id}")
            if skill["current_snapshot_id"] != member.baseline_snapshot_id:
                raise ValueError(f"skill snapshot changed: {member.skill_id}")
            owner = connection.execute(
                "SELECT group_id FROM sync_group_members WHERE skill_id = ?",
                (member.skill_id,),
            ).fetchone()
            if owner is not None:
                raise ValueError(f"skill already belongs to sync group: {member.skill_id}")
        connection.execute(
            """
            INSERT INTO sync_groups(
                group_id, name, authority_skill_id, policy, baseline_revision, status, created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group.group_id,
                group.name,
                group.authority_skill_id,
                group.policy.value,
                group.baseline_revision,
                group.status.value,
                now,
                now,
            ),
        )
        for member in group.members:
            connection.execute(
                """
                INSERT INTO sync_group_members(
                    group_id, skill_id, role, baseline_snapshot_id, baseline_content_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    group.group_id,
                    member.skill_id,
                    member.role.value,
                    member.baseline_snapshot_id,
                    member.baseline_content_hash,
                ),
            )

    def get_sync_group(self, group_id: str) -> SyncGroup | None:
        with self.catalog.database.connect() as connection:
            group = connection.execute("SELECT * FROM sync_groups WHERE group_id = ?", (group_id,)).fetchone()
            if group is None:
                return None
            members = connection.execute(
                """
                SELECT skill_id, role, baseline_snapshot_id, baseline_content_hash
                FROM sync_group_members
                WHERE group_id = ?
                ORDER BY CASE role WHEN 'authority' THEN 0 ELSE 1 END, skill_id
                """,
                (group_id,),
            ).fetchall()
        return SyncGroup(
            group_id=group["group_id"],
            name=group["name"],
            authority_skill_id=group["authority_skill_id"],
            policy=group["policy"],
            baseline_revision=group["baseline_revision"],
            status=group["status"],
            members=[
                SyncGroupMember(
                    skill_id=member["skill_id"],
                    role=member["role"],
                    baseline_snapshot_id=member["baseline_snapshot_id"],
                    baseline_content_hash=member["baseline_content_hash"],
                )
                for member in members
            ],
        )

    def list_sync_groups(self) -> list[SyncGroup]:
        with self.catalog.database.connect() as connection:
            group_ids = [row["group_id"] for row in connection.execute(
                "SELECT group_id FROM sync_groups ORDER BY group_id"
            ).fetchall()]
        return [group for group_id in group_ids if (group := self.get_sync_group(group_id)) is not None]

    def update_sync_group_status(self, group_id: str, status: SyncGroupStatus) -> None:
        """Refresh derived state without modifying the group's immutable baselines."""
        with self.catalog.database.connect() as connection:
            connection.execute(
                "UPDATE sync_groups SET status = ?, updated_at = ? WHERE group_id = ?",
                (status.value, datetime.now(UTC).isoformat(), group_id),
            )

    def delete_sync_group(self, group_id: str) -> None:
        """Delete only group metadata; its member rows cascade and Skills remain intact."""
        with self.catalog.database.connect() as connection:
            connection.execute("DELETE FROM sync_groups WHERE group_id = ?", (group_id,))

    def save_run(
        self,
        run_id: str,
        *,
        kind: str,
        revision: str,
        groups: list[CandidateGroupSummary],
        snapshots_by_skill: dict[str, SkillSnapshot],
        findings: list[Finding] | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.catalog.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO analysis_runs(run_id, kind, revision, started_at, completed_at, status,
                                              parameters_json, warnings_json)
                    VALUES (?, ?, ?, ?, ?, 'complete', ?, '[]')
                    """,
                    (
                        run_id,
                        kind,
                        revision,
                        now,
                        now,
                        json.dumps(
                            {"local_findings": [item.model_dump(mode="json") for item in (findings or [])]},
                            ensure_ascii=False,
                        ),
                    ),
                )
                for group in groups:
                    stored_group_id = _stored_group_id(run_id, group.group_id)
                    connection.execute(
                        """
                        INSERT INTO candidate_groups(group_id, run_id, kind, score, status, created_at)
                        VALUES (?, ?, ?, ?, 'open', ?)
                        """,
                        (stored_group_id, run_id, group.relation.value, group.similarity, now),
                    )
                    for skill_id in group.member_skill_ids:
                        connection.execute(
                            "INSERT INTO group_members(group_id, snapshot_id, role) VALUES (?, ?, 'member')",
                            (stored_group_id, snapshots_by_skill[skill_id].snapshot_id),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def save_source_preflight(self, preflight: SourcePreflight) -> None:
        """Store local source evidence for the exact bytes that were analyzed."""
        with self.catalog.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_preflights(preflight_id, source, status, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    preflight.run_id,
                    preflight.source,
                    "blocked" if preflight.deterministic_blockers else "complete",
                    json.dumps(preflight.model_dump(mode="json"), ensure_ascii=False),
                    preflight.created_at.isoformat(),
                ),
            )

    def get_source_preflight(self, run_id: str) -> SourcePreflight:
        with self.catalog.database.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM source_preflights WHERE preflight_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"unknown source preflight: {run_id}")
        return SourcePreflight.model_validate_json(row["result_json"])

    def latest_source_preflight(self, source_hash: str) -> SourcePreflight | None:
        with self.catalog.database.connect() as connection:
            rows = connection.execute(
                "SELECT result_json FROM source_preflights ORDER BY created_at DESC, preflight_id DESC"
            ).fetchall()
        for row in rows:
            preflight = SourcePreflight.model_validate_json(row["result_json"])
            if preflight.source_hash == source_hash:
                return preflight
        return None

    def has_agent_review(self, run_id: str) -> bool:
        with self.catalog.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM agent_reviews
                JOIN candidate_groups ON candidate_groups.group_id = agent_reviews.group_id
                WHERE candidate_groups.run_id = ?
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return row is not None

    def evidence_members(self, run_id: str, group_id: str) -> tuple[str, list[EvidenceMember]]:
        stored_group_id = _stored_group_id(run_id, group_id)
        with self.catalog.database.connect() as connection:
            run = connection.execute(
                "SELECT revision FROM analysis_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"unknown analysis run: {run_id}")
            group = connection.execute(
                "SELECT 1 FROM candidate_groups WHERE group_id = ? AND run_id = ?",
                (stored_group_id, run_id),
            ).fetchone()
            if group is None:
                raise ValueError("group does not belong to analysis run")
            rows = connection.execute(
                """
                SELECT skill_snapshots.*, library_roots.provider, library_roots.scope,
                       library_roots.project_path, library_roots.path AS root_path
                FROM group_members
                JOIN skill_snapshots ON skill_snapshots.snapshot_id = group_members.snapshot_id
                JOIN library_roots ON library_roots.root_id = skill_snapshots.root_id
                WHERE group_members.group_id = ?
                ORDER BY CASE library_roots.provider
                             WHEN 'codex' THEN 0
                             WHEN 'claude' THEN 1
                             WHEN 'cursor' THEN 2
                             ELSE 3
                         END,
                         skill_snapshots.skill_id
                """,
                (stored_group_id,),
            ).fetchall()
        return run["revision"], [
            EvidenceMember(
                snapshot=self._snapshot(row),
                provider=row["provider"],
                scope=row["scope"],
                project_path=row["project_path"],
                root_path=row["root_path"],
            )
            for row in rows
        ]

    def review_context(self, run_id: str) -> ReviewContext:
        """Return only the metadata needed to validate and render an Agent review."""
        with self.catalog.database.connect() as connection:
            return self._review_context(connection, run_id)

    def save_review(
        self,
        *,
        review_id: str,
        context: ReviewContext,
        decisions: list[GroupDecision],
        markdown_path: Path,
        json_path: Path,
        markdown: str,
        json_payload: dict[str, object],
        markdown_bytes: bytes,
        json_bytes: bytes,
    ) -> None:
        """Commit decisions and report index rows as a single catalog transaction."""
        from skillcheck.governance.reviews import StaleAnalysisError, content_hash

        now = datetime.now(UTC).isoformat()
        with self.catalog.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._review_context(connection, context.run_id)
                if not current.is_current or current.revision != context.revision:
                    raise StaleAnalysisError("analysis snapshots have changed; analyze again before saving")
                stored_group_ids = {
                    item.group_id: _stored_group_id(context.run_id, item.group_id) for item in context.groups
                }
                for index, decision in enumerate(decisions):
                    connection.execute(
                        """
                        INSERT INTO agent_reviews(review_id, group_id, agent, decision, rationale, payload_json, created_at)
                        VALUES (?, ?, 'current-agent', ?, ?, ?, ?)
                        """,
                        (
                            f"{review_id}:{index}",
                            stored_group_ids[decision.group_id],
                            decision.decision.value,
                            decision.reason,
                            json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
                            now,
                        ),
                    )
                for report_format, path in (
                    ("markdown", markdown_path),
                    ("json", json_path),
                ):
                    connection.execute(
                        """
                        INSERT INTO reports(report_id, run_id, format, path, content_hash, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{review_id}:{report_format}",
                            context.run_id,
                            report_format,
                            str(path),
                            content_hash(
                                markdown_bytes if report_format == "markdown" else json_bytes
                            ),
                            now,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _review_context(self, connection, run_id: str) -> ReviewContext:
        run = connection.execute(
            "SELECT revision, status, parameters_json FROM analysis_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            raise ValueError(f"unknown analysis run: {run_id}")
        if run["status"] != "complete":
            raise ValueError("analysis run is not complete")
        parameters = json.loads(run["parameters_json"] or "{}")
        rows = connection.execute(
            """
            SELECT candidate_groups.group_id AS stored_group_id,
                   candidate_groups.kind,
                   candidate_groups.score,
                   group_members.snapshot_id,
                   skill_snapshots.skill_id,
                   skills.current_snapshot_id
            FROM candidate_groups
            JOIN group_members ON group_members.group_id = candidate_groups.group_id
            JOIN skill_snapshots ON skill_snapshots.snapshot_id = group_members.snapshot_id
            LEFT JOIN skills ON skills.skill_id = skill_snapshots.skill_id
            WHERE candidate_groups.run_id = ?
            ORDER BY candidate_groups.group_id, skill_snapshots.skill_id
            """,
            (run_id,),
        ).fetchall()
        grouped: dict[str, ReviewGroup] = {}
        current = True
        for row in rows:
            group_id = _public_group_id(run_id, row["stored_group_id"])
            group = grouped.get(group_id)
            if group is None:
                group = ReviewGroup(
                    group_id=group_id,
                    relation=row["kind"],
                    similarity=row["score"],
                    member_skill_ids=[],
                    snapshot_ids=[],
                )
                grouped[group_id] = group
            group.member_skill_ids.append(row["skill_id"])
            group.snapshot_ids.append(row["snapshot_id"])
            if row["current_snapshot_id"] != row["snapshot_id"]:
                current = False
        latest = connection.execute(
            "SELECT revision FROM sync_events ORDER BY completed_at DESC, event_id DESC LIMIT 1"
        ).fetchone()
        if latest is not None and not str(run["revision"]).startswith("sha256:"):
            current = current and latest["revision"] == run["revision"]
        return ReviewContext(
            run_id=run_id,
            revision=run["revision"],
            groups=list(grouped.values()),
            local_findings=parameters.get("local_findings", []),
            is_current=current,
        )

    @staticmethod
    def _snapshot(row) -> SkillSnapshot:
        return SkillSnapshot(
            snapshot_id=row["snapshot_id"],
            skill_id=row["skill_id"],
            root_id=row["root_id"],
            relative_path=row["relative_path"],
            name=row["name"],
            description=row["description"],
            body=row["body"],
            content_hash=row["content_hash"],
            status=row["status"],
            tools=json.loads(row["tools_json"]),
            permissions=json.loads(row["permissions_json"]),
            environments=json.loads(row["environments_json"]),
            inputs=json.loads(row["inputs_json"]),
            outputs=json.loads(row["outputs_json"]),
            indexed_at=row["indexed_at"],
            parse_error=row["parse_error"],
        )


def _stored_group_id(run_id: str, group_id: str) -> str:
    return f"{run_id}:{group_id}"


def _public_group_id(run_id: str, stored_group_id: str) -> str:
    prefix = f"{run_id}:"
    return stored_group_id.removeprefix(prefix)
