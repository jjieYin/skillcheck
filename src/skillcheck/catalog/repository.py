from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, SkillSnapshot, SkillStatus, SyncEvent


@dataclass(frozen=True)
class VectorRecord:
    snapshot_id: str
    model: str
    content_hash: str
    dimensions: int
    vector: np.ndarray


class CatalogRepository:
    """Persistence boundary for roots and immutable Skill snapshots."""

    def __init__(self, database: CatalogDatabase) -> None:
        self.database = database

    def upsert_root(self, root: LibraryRoot) -> None:
        now = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO library_roots
                    (root_id, path, provider, scope, project_path, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_id) DO UPDATE SET
                    path=excluded.path,
                    provider=excluded.provider,
                    scope=excluded.scope,
                    project_path=excluded.project_path,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    root.root_id,
                    str(root.path),
                    root.provider,
                    root.scope.value,
                    str(root.project_path) if root.project_path is not None else None,
                    int(root.enabled),
                    now,
                    now,
                ),
            )

    def list_roots(self) -> list[LibraryRoot]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM library_roots ORDER BY root_id").fetchall()
        return [
            LibraryRoot(
                root_id=row["root_id"],
                path=Path(row["path"]),
                provider=row["provider"],
                scope=row["scope"],
                project_path=Path(row["project_path"]) if row["project_path"] else None,
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def upsert_snapshot(self, snapshot: SkillSnapshot) -> None:
        now = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO skills
                        (skill_id, root_id, relative_path, status, current_snapshot_id,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(skill_id) DO UPDATE SET
                        root_id=excluded.root_id,
                        relative_path=excluded.relative_path,
                        status=excluded.status,
                        current_snapshot_id=excluded.current_snapshot_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        snapshot.skill_id,
                        snapshot.root_id,
                        snapshot.relative_path,
                        snapshot.status.value,
                        snapshot.snapshot_id,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO skill_snapshots
                        (snapshot_id, skill_id, root_id, relative_path, name, description, body,
                         content_hash, status, tools_json, permissions_json, environments_json,
                         inputs_json, outputs_json, indexed_at, parse_error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.skill_id,
                        snapshot.root_id,
                        snapshot.relative_path,
                        snapshot.name,
                        snapshot.description,
                        snapshot.body,
                        snapshot.content_hash,
                        snapshot.status.value,
                        _json(snapshot.tools),
                        _json(snapshot.permissions),
                        _json(snapshot.environments),
                        _json(snapshot.inputs),
                        _json(snapshot.outputs),
                        snapshot.indexed_at.isoformat(),
                        snapshot.parse_error,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM skill_fts
                    WHERE snapshot_id IN (
                        SELECT snapshot_id FROM skill_snapshots WHERE skill_id = ?
                    )
                    """,
                    (snapshot.skill_id,),
                )
                if snapshot.status is SkillStatus.ACTIVE:
                    connection.execute(
                        """
                        INSERT INTO skill_fts(snapshot_id, name, description, body)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            snapshot.snapshot_id,
                            snapshot.name,
                            snapshot.description,
                            snapshot.body,
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def mark_missing(self, skill_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE skills SET status = ?, updated_at = ? WHERE skill_id = ?",
                    (SkillStatus.MISSING.value, _now(), skill_id),
                )
                connection.execute(
                    """
                    DELETE FROM skill_fts
                    WHERE snapshot_id = (
                        SELECT current_snapshot_id FROM skills WHERE skill_id = ?
                    )
                    """,
                    (skill_id,),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get_current_skill(self, skill_id: str) -> SkillSnapshot | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT skill_snapshots.*, skills.status AS skill_status
                FROM skills
                JOIN skill_snapshots
                  ON skill_snapshots.snapshot_id = skills.current_snapshot_id
                WHERE skills.skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
        return _snapshot_from_row(row, row["skill_status"]) if row else None

    def get_current_skills(self, skill_ids: Iterable[str]) -> dict[str, SkillSnapshot | None]:
        """Read current snapshots for all requested IDs from one database view."""
        requested = list(dict.fromkeys(skill_ids))
        current: dict[str, SkillSnapshot | None] = {skill_id: None for skill_id in requested}
        if not requested:
            return current
        placeholders = ", ".join("?" for _ in requested)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT skill_snapshots.*, skills.status AS skill_status
                FROM skills
                JOIN skill_snapshots
                  ON skill_snapshots.snapshot_id = skills.current_snapshot_id
                WHERE skills.skill_id IN ({placeholders})
                """,
                requested,
            ).fetchall()
        for row in rows:
            current[row["skill_id"]] = _snapshot_from_row(row, row["skill_status"])
        return current

    def list_current_skills(self, search: str | None = None) -> list[SkillSnapshot]:
        parameters: tuple[str, ...] = ()
        if search is None:
            query = """
                SELECT skill_snapshots.*, skills.status AS skill_status
                FROM skills
                JOIN skill_snapshots
                  ON skill_snapshots.snapshot_id = skills.current_snapshot_id
                WHERE skills.status = 'active'
                ORDER BY skills.skill_id
            """
        else:
            query = """
                SELECT skill_snapshots.*, skills.status AS skill_status
                FROM skill_fts
                JOIN skill_snapshots
                  ON skill_snapshots.snapshot_id = skill_fts.snapshot_id
                JOIN skills
                  ON skills.current_snapshot_id = skill_snapshots.snapshot_id
                WHERE skills.status = 'active' AND skill_fts MATCH ?
                ORDER BY skills.skill_id
            """
            parameters = (search,)
        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_snapshot_from_row(row, row["skill_status"]) for row in rows]

    def list_snapshots(self, skill_id: str) -> list[SkillSnapshot]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM skill_snapshots
                WHERE skill_id = ?
                ORDER BY indexed_at, snapshot_id
                """,
                (skill_id,),
            ).fetchall()
        return [_snapshot_from_row(row) for row in rows]

    def save_vector(
        self,
        snapshot_id: str,
        model: str,
        content_hash: str,
        vector: Iterable[float] | np.ndarray,
    ) -> None:
        encoded = np.ascontiguousarray(np.asarray(list(vector), dtype=np.float32).reshape(-1))
        if encoded.size == 0:
            raise ValueError("embedding vector cannot be empty")
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO vectors
                    (snapshot_id, model, dimensions, content_hash, vector, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id, model) DO UPDATE SET
                    dimensions=excluded.dimensions,
                    content_hash=excluded.content_hash,
                    vector=excluded.vector,
                    created_at=excluded.created_at
                """,
                (
                    snapshot_id,
                    model,
                    int(encoded.size),
                    content_hash,
                    encoded.tobytes(),
                    _now(),
                ),
            )

    def get_vectors(self, model: str | None = None) -> list[VectorRecord]:
        query = "SELECT * FROM vectors"
        parameters: tuple[str, ...] = ()
        if model is not None:
            query += " WHERE model = ?"
            parameters = (model,)
        query += " ORDER BY snapshot_id, model"
        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            VectorRecord(
                snapshot_id=row["snapshot_id"],
                model=row["model"],
                content_hash=row["content_hash"],
                dimensions=row["dimensions"],
                vector=np.frombuffer(
                    row["vector"], dtype=np.float32, count=row["dimensions"]
                ).copy(),
            )
            for row in rows
        ]

    def record_sync_event(self, event: SyncEvent) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_events
                    (event_id, revision, started_at, completed_at, added, updated, removed,
                     invalid, warnings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    revision=excluded.revision,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    added=excluded.added,
                    updated=excluded.updated,
                    removed=excluded.removed,
                    invalid=excluded.invalid,
                    warnings_json=excluded.warnings_json
                """,
                (
                    event.event_id,
                    event.revision,
                    event.started_at.isoformat(),
                    event.completed_at.isoformat(),
                    event.added,
                    event.updated,
                    event.removed,
                    event.invalid,
                    _json(event.warnings),
                ),
            )


def _snapshot_from_row(row: sqlite3.Row, status: str | None = None) -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id=row["snapshot_id"],
        skill_id=row["skill_id"],
        root_id=row["root_id"],
        relative_path=row["relative_path"],
        name=row["name"],
        description=row["description"],
        body=row["body"],
        content_hash=row["content_hash"],
        status=status or row["status"],
        tools=json.loads(row["tools_json"]),
        permissions=json.loads(row["permissions_json"]),
        environments=json.loads(row["environments_json"]),
        inputs=json.loads(row["inputs_json"]),
        outputs=json.loads(row["outputs_json"]),
        indexed_at=row["indexed_at"],
        parse_error=row["parse_error"],
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _now() -> str:
    return datetime.now(UTC).isoformat()
