from __future__ import annotations

import json
import re
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any


class IncompatibleCatalogError(RuntimeError):
    """Raised when a path contains data that is not a v0.4 catalog."""


class CatalogDatabase:
    """Owns creation and compatibility checks for the immutable v0.4 schema."""

    schema_version_number = 4

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Create a new catalog or verify that an existing one is v4."""
        if self.path.exists() and self.path.stat().st_size > 0:
            self._verify_existing_catalog()
            return

        self._create_schema()

    def _verify_existing_catalog(self) -> None:
        try:
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None or row["value"] != str(self.schema_version_number):
                    raise IncompatibleCatalogError(
                        "Existing catalog is incompatible; reinitialize it for v0.4."
                    )
                if not self._expected_tables() <= self._table_names(connection):
                    raise IncompatibleCatalogError(
                        "Existing catalog is incomplete; reinitialize it for v0.4."
                    )
                if not self._has_expected_structure(connection):
                    raise IncompatibleCatalogError(
                        "Existing catalog has an incompatible schema; reinitialize it for v0.4."
                    )
        except IncompatibleCatalogError:
            raise
        except sqlite3.DatabaseError as error:
            raise IncompatibleCatalogError(
                "Existing catalog is invalid; reinitialize it for v0.4."
            ) from error

    def _create_schema(self) -> None:
        schema = self._schema_sql()
        statements = [statement.strip() for statement in schema.split(";") if statement.strip()]
        try:
            with self.connect() as connection:
                connection.execute("BEGIN")
                try:
                    for statement in statements:
                        connection.execute(statement)
                except Exception:
                    connection.rollback()
                    raise
                connection.commit()
        except sqlite3.DatabaseError as error:
            raise IncompatibleCatalogError(
                "Catalog schema could not be created; reinitialize the catalog path."
            ) from error

    def schema_version(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"]) if row else 0

    def table_names(self) -> set[str]:
        with self.connect() as connection:
            return self._table_names(connection)

    @staticmethod
    def json_dumps(value: Any) -> str:
        """Serialize catalog JSON without escaping Unicode characters."""
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
        ).fetchall()
        return {row["name"] for row in rows}

    @classmethod
    def _has_expected_structure(cls, connection: sqlite3.Connection) -> bool:
        actual = cls._schema_objects(connection)
        expected = cls._canonical_schema_objects()
        for table in cls._expected_tables():
            actual_object = actual.get(table)
            expected_object = expected.get(table)
            if actual_object is None or expected_object is None:
                return False
            if actual_object["type"] != expected_object["type"]:
                return False
            if cls._normalize_definition(actual_object["sql"]) != cls._normalize_definition(
                expected_object["sql"]
            ):
                return False
        return True

    @classmethod
    def _canonical_schema_objects(cls) -> dict[str, sqlite3.Row]:
        with sqlite3.connect(":memory:") as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript(cls._schema_sql())
            return cls._schema_objects(connection)

    @classmethod
    def _schema_sql(cls) -> str:
        return files("skillcheck.catalog").joinpath("schema.sql").read_text(encoding="utf-8")

    @staticmethod
    def _normalize_definition(definition: str | None) -> str:
        return re.sub(r"\s+", "", definition or "").lower()

    @classmethod
    def _schema_objects(cls, connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
        tables = tuple(cls._expected_tables())
        placeholders = ",".join("?" for _ in tables)
        rows = connection.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name IN " f"({placeholders})",
            tables,
        ).fetchall()
        return {row["name"]: row for row in rows}

    @classmethod
    def _expected_tables(cls) -> set[str]:
        return {
            "schema_meta",
            "library_roots",
            "skills",
            "skill_snapshots",
            "sync_events",
            "vectors",
            "analysis_runs",
            "candidate_groups",
            "group_members",
            "evidence",
            "agent_reviews",
            "reports",
            "source_preflights",
            "install_plans",
            "skill_fts",
        }

    @staticmethod
    def _expected_columns() -> dict[str, list[str]]:
        return {
            "schema_meta": ["key", "value"],
            "library_roots": [
                "root_id",
                "path",
                "provider",
                "scope",
                "project_path",
                "enabled",
                "created_at",
                "updated_at",
            ],
            "skills": [
                "skill_id",
                "root_id",
                "relative_path",
                "status",
                "current_snapshot_id",
                "created_at",
                "updated_at",
            ],
            "skill_snapshots": [
                "snapshot_id",
                "skill_id",
                "root_id",
                "relative_path",
                "name",
                "description",
                "body",
                "content_hash",
                "status",
                "tools_json",
                "permissions_json",
                "environments_json",
                "inputs_json",
                "outputs_json",
                "indexed_at",
                "parse_error",
            ],
            "sync_events": [
                "event_id",
                "revision",
                "started_at",
                "completed_at",
                "added",
                "updated",
                "removed",
                "invalid",
                "warnings_json",
            ],
            "vectors": [
                "snapshot_id",
                "model",
                "dimensions",
                "content_hash",
                "vector",
                "created_at",
            ],
            "analysis_runs": [
                "run_id",
                "kind",
                "revision",
                "started_at",
                "completed_at",
                "status",
                "parameters_json",
                "warnings_json",
            ],
            "candidate_groups": ["group_id", "run_id", "kind", "score", "status", "created_at"],
            "group_members": ["group_id", "snapshot_id", "role"],
            "evidence": ["evidence_id", "group_id", "kind", "content_json", "created_at"],
            "agent_reviews": [
                "review_id",
                "group_id",
                "agent",
                "decision",
                "rationale",
                "payload_json",
                "created_at",
            ],
            "reports": ["report_id", "run_id", "format", "path", "content_hash", "created_at"],
            "source_preflights": ["preflight_id", "source", "status", "result_json", "created_at"],
            "install_plans": [
                "plan_id",
                "source_preflight_id",
                "status",
                "plan_json",
                "created_at",
                "updated_at",
            ],
        }
