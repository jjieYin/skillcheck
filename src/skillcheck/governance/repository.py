from __future__ import annotations

import json
from datetime import UTC, datetime

from skillcheck.catalog.models import SkillSnapshot
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance.models import CandidateGroupSummary


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
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.catalog.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO analysis_runs(run_id, kind, revision, started_at, completed_at, status,
                                              parameters_json, warnings_json)
                    VALUES (?, ?, ?, ?, ?, 'complete', '{}', '[]')
                    """,
                    (run_id, kind, revision, now, now),
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
