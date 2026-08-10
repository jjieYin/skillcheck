from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from skillcheck.storage.migrations import statements_for


LEGACY_SCHEMA = """
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


class Database:
    latest_version = 2

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _bootstrap_legacy(self) -> None:
        with self.connect() as connection:
            connection.executescript(LEGACY_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1')"
            )

    def migration_sql(self, version: int) -> tuple[str, ...]:
        return statements_for(version)

    @staticmethod
    def _current_version(connection: sqlite3.Connection) -> int:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "schema_migrations" in tables:
            row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            if row and row["version"] is not None:
                return int(row["version"])
        if "schema_meta" in tables:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row:
                return int(row["value"])
        return 0

    def migrate(self) -> None:
        self._bootstrap_legacy()
        with self.connect() as connection:
            current = self._current_version(connection)
            if current >= self.latest_version:
                return
            connection.execute("BEGIN")
            try:
                for version in range(current + 1, self.latest_version + 1):
                    for statement in self.migration_sql(version):
                        connection.execute(statement)
                    connection.execute(
                        "INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, datetime.now(UTC).isoformat()),
                    )
                    connection.execute(
                        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                        (str(version),),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def schema_version(self) -> int:
        with self.connect() as connection:
            return self._current_version(connection)

    def table_names(self) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {row["name"] for row in rows}
