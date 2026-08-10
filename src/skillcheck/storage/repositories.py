from __future__ import annotations

import json

from skillcheck.models.report import ScanRun
from skillcheck.storage.database import Database


class RunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, run: ScanRun) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO scan_runs
                (run_id, started_at, completed_at, scopes_json, index_revision,
                 capabilities_json, skill_count, finding_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    json.dumps(run.scopes, ensure_ascii=False),
                    run.index_revision,
                    json.dumps(run.capabilities, ensure_ascii=False),
                    run.skill_count,
                    run.finding_count,
                    run.status,
                ),
            )

    def get(self, run_id: str) -> ScanRun | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM scan_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return ScanRun(
            run_id=row["run_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            scopes=json.loads(row["scopes_json"]),
            index_revision=row["index_revision"],
            capabilities=json.loads(row["capabilities_json"]),
            skill_count=row["skill_count"],
            finding_count=row["finding_count"],
            status=row["status"],
        )


class TableRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def count(self, table: str) -> int:
        if table not in {"scan_runs", "governance_groups", "reports", "agent_reviews"}:
            raise ValueError(f"不允许查询表：{table}")
        with self.database.connect() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])
