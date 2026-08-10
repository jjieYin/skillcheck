from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from skillcheck.catalog.models import SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance.models import CandidateGroupSummary
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


class GovernanceRepository:
    """Persist bounded local analysis results in the catalog's v4 tables."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self.catalog = catalog

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

    def evidence_members(self, run_id: str, group_id: str) -> tuple[str, list[SkillSnapshot]]:
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
                SELECT skill_snapshots.*
                FROM group_members
                JOIN skill_snapshots ON skill_snapshots.snapshot_id = group_members.snapshot_id
                WHERE group_members.group_id = ?
                ORDER BY skill_snapshots.skill_id
                """,
                (stored_group_id,),
            ).fetchall()
        return run["revision"], [self._snapshot(row) for row in rows]

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
            if row["current_snapshot_id"] is not None and row["current_snapshot_id"] != row["snapshot_id"]:
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
