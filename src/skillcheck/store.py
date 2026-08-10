from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from skillcheck.models import Provider, Scope, SkillRecord
from skillcheck.storage.database import Database


@dataclass(frozen=True)
class VectorRow:
    skill_id: str
    vector: np.ndarray
    model: str
    content_hash: str


class SkillStore:
    """SQLite-backed local inventory and embedding repository."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    provider TEXT,
                    scope TEXT,
                    body TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    tools_json TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    environments_json TEXT NOT NULL,
                    inputs_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS installations (
                    skill_id TEXT PRIMARY KEY REFERENCES skills(skill_id) ON DELETE CASCADE,
                    root_path TEXT NOT NULL,
                    provider TEXT,
                    scope TEXT
                );
                CREATE TABLE IF NOT EXISTS vectors (
                    skill_id TEXT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (skill_id, model)
                );
                CREATE INDEX IF NOT EXISTS idx_skills_content_hash ON skills(content_hash);
                CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1')"
            )
        Database(self.path).migrate()

    def upsert(
        self,
        skill: SkillRecord,
        *,
        vector: np.ndarray | None = None,
        model: str | None = None,
    ) -> None:
        with self._connect() as connection:
            _upsert_skill(connection, skill)
            if vector is not None:
                if not model:
                    raise ValueError("model is required when vector is provided")
                encoded = _encode_vector(vector)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO vectors
                    (skill_id, model, content_hash, dimensions, vector)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (skill.skill_id, model, skill.content_hash, encoded.size, encoded.tobytes()),
                )

    def replace_inventory(
        self,
        skills: Iterable[SkillRecord],
        vectors: dict[str, np.ndarray],
        *,
        model: str,
    ) -> None:
        records = list(skills)
        ids = {skill.skill_id for skill in records}
        with self._connect() as connection:
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM skills WHERE skill_id NOT IN ({placeholders})", tuple(ids)
                )
            else:
                connection.execute("DELETE FROM skills")
            for skill in records:
                _upsert_skill(connection, skill)
                vector = vectors.get(skill.skill_id)
                if vector is not None:
                    encoded = _encode_vector(vector)
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO vectors
                        (skill_id, model, content_hash, dimensions, vector)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (skill.skill_id, model, skill.content_hash, encoded.size, encoded.tobytes()),
                    )

    def remove_missing(self, skill_ids: Iterable[str]) -> int:
        ids = list(dict.fromkeys(skill_ids))
        with self._connect() as connection:
            if not ids:
                cursor = connection.execute("DELETE FROM skills")
                return cursor.rowcount
            placeholders = ",".join("?" for _ in ids)
            cursor = connection.execute(
                f"DELETE FROM skills WHERE skill_id NOT IN ({placeholders})", tuple(ids)
            )
            return cursor.rowcount

    def list_skills(
        self,
        *,
        provider: Provider | str | None = None,
        root_path: Path | str | None = None,
    ) -> list[SkillRecord]:
        query = "SELECT * FROM skills"
        clauses: list[str] = []
        params: list[str] = []
        if provider is not None:
            clauses.append("provider = ?")
            params.append(provider.value if isinstance(provider, Provider) else str(provider))
        if root_path is not None:
            clauses.append("root_path = ?")
            params.append(str(Path(root_path).expanduser().resolve()))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY skill_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_skill_from_row(row) for row in rows]

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
        return _skill_from_row(row) if row else None

    def get_vector_rows(self, *, model: str | None = None) -> list[VectorRow]:
        query = "SELECT skill_id, model, content_hash, dimensions, vector FROM vectors"
        params: tuple[str, ...] = ()
        if model is not None:
            query += " WHERE model = ?"
            params = (model,)
        query += " ORDER BY skill_id"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            VectorRow(
                skill_id=row["skill_id"],
                model=row["model"],
                content_hash=row["content_hash"],
                vector=np.frombuffer(row["vector"], dtype=np.float32, count=row["dimensions"]).copy(),
            )
            for row in rows
        ]

    def needs_embedding(self, skill: SkillRecord, model: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT content_hash FROM vectors
                WHERE skill_id = ? AND model = ?
                """,
                (skill.skill_id, model),
            ).fetchone()
        return row is None or row["content_hash"] != skill.content_hash

    def close(self) -> None:
        """Compatibility hook for callers that manage stores as resources."""


def _upsert_skill(connection: sqlite3.Connection, skill: SkillRecord) -> None:
    connection.execute(
        """
        INSERT INTO skills
        (skill_id, name, description, root_path, provider, scope, body, content_hash,
         tools_json, permissions_json, environments_json, inputs_json, outputs_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(skill_id) DO UPDATE SET
            name=excluded.name,
            description=excluded.description,
            root_path=excluded.root_path,
            provider=excluded.provider,
            scope=excluded.scope,
            body=excluded.body,
            content_hash=excluded.content_hash,
            tools_json=excluded.tools_json,
            permissions_json=excluded.permissions_json,
            environments_json=excluded.environments_json,
            inputs_json=excluded.inputs_json,
            outputs_json=excluded.outputs_json
        """,
        (
            skill.skill_id,
            skill.name,
            skill.description,
            str(skill.root_path),
            skill.provider.value if skill.provider else None,
            skill.scope.value if skill.scope else None,
            skill.body,
            skill.content_hash,
            json.dumps(skill.tools, ensure_ascii=False),
            json.dumps(skill.permissions, ensure_ascii=False),
            json.dumps(skill.environments, ensure_ascii=False),
            json.dumps(skill.inputs, ensure_ascii=False),
            json.dumps(skill.outputs, ensure_ascii=False),
        ),
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO installations(skill_id, root_path, provider, scope)
        VALUES (?, ?, ?, ?)
        """,
        (
            skill.skill_id,
            str(skill.root_path),
            skill.provider.value if skill.provider else None,
            skill.scope.value if skill.scope else None,
        ),
    )


def _skill_from_row(row: sqlite3.Row) -> SkillRecord:
    return SkillRecord(
        skill_id=row["skill_id"],
        name=row["name"],
        description=row["description"],
        root_path=Path(row["root_path"]),
        provider=Provider(row["provider"]) if row["provider"] else None,
        scope=Scope(row["scope"]) if row["scope"] else None,
        body=row["body"],
        content_hash=row["content_hash"],
        tools=json.loads(row["tools_json"]),
        permissions=json.loads(row["permissions_json"]),
        environments=json.loads(row["environments_json"]),
        inputs=json.loads(row["inputs_json"]),
        outputs=json.loads(row["outputs_json"]),
    )


def _encode_vector(vector: np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    if array.size == 0:
        raise ValueError("embedding vector cannot be empty")
    return np.ascontiguousarray(array)
