from __future__ import annotations

import json
import re
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

from skillcheck.catalog import migrations


class IncompatibleCatalogError(RuntimeError):
    """Raised when a path contains data that is not a compatible catalog."""


class CatalogDatabase:
    """Owns creation and compatibility checks for the v5 schema."""

    schema_version_number = 5

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Create a new catalog, migrate v4, or verify an existing v5 catalog."""
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
                if row is None:
                    raise IncompatibleCatalogError(
                        "Existing catalog is incompatible; reinitialize it for v0.5."
                    )
                if row["value"] == "4":
                    self._migrate_v4_to_v5(connection)
                elif row["value"] != str(self.schema_version_number):
                    raise IncompatibleCatalogError(
                        "Existing catalog is incompatible; reinitialize it for v0.5."
                    )
                if not self._expected_tables() <= self._table_names(connection):
                    raise IncompatibleCatalogError(
                        "Existing catalog is incomplete; reinitialize it for v0.5."
                    )
                if not self._has_expected_structure(connection):
                    raise IncompatibleCatalogError(
                        "Existing catalog has an incompatible schema; reinitialize it for v0.5."
                    )
        except IncompatibleCatalogError:
            raise
        except sqlite3.DatabaseError as error:
            raise IncompatibleCatalogError(
                "Existing catalog is invalid; reinitialize it for v0.5."
            ) from error

    @staticmethod
    def _migrate_v4_to_v5(connection: sqlite3.Connection) -> None:
        statements = [
            statement.strip() for statement in migrations.V4_TO_V5_SQL.split(";") if statement.strip()
        ]
        try:
            connection.execute("BEGIN IMMEDIATE")
            if not CatalogDatabase._has_expected_v4_structure(connection):
                raise IncompatibleCatalogError(
                    "Existing catalog has an incompatible v0.4 schema; reinitialize it."
                )
            for statement in statements:
                connection.execute(statement)
            if not CatalogDatabase._has_expected_structure(connection):
                raise IncompatibleCatalogError(
                    "Catalog migration to v0.5 produced an incompatible schema."
                )
            connection.commit()
        except (IncompatibleCatalogError, sqlite3.DatabaseError) as error:
            connection.rollback()
            raise IncompatibleCatalogError(
                "Catalog migration to v0.5 failed; existing catalog was not changed."
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
        return cls._has_expected_objects(
            connection,
            cls._expected_schema_objects(),
            cls._schema_sql(),
        )

    @classmethod
    def _has_expected_v4_structure(cls, connection: sqlite3.Connection) -> bool:
        return cls._has_expected_objects(
            connection,
            cls._expected_v4_schema_objects(),
            cls._v4_schema_sql(),
        )

    @classmethod
    def _has_expected_objects(
        cls, connection: sqlite3.Connection, object_names: set[str], schema: str
    ) -> bool:
        actual = cls._schema_objects(connection, object_names)
        expected = cls._canonical_schema_objects(schema, object_names)
        for object_name in object_names:
            actual_object = actual.get(object_name)
            expected_object = expected.get(object_name)
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
    def _canonical_schema_objects(
        cls, schema: str, object_names: set[str]
    ) -> dict[str, sqlite3.Row]:
        with sqlite3.connect(":memory:") as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript(schema)
            return cls._schema_objects(connection, object_names)

    @classmethod
    def _schema_sql(cls) -> str:
        return files("skillcheck.catalog").joinpath("schema.sql").read_text(encoding="utf-8")

    @classmethod
    def _v4_schema_sql(cls) -> str:
        schema = cls._schema_sql()
        schema = schema.replace(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '5');",
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', '4');",
        )
        schema = re.sub(
            r"\nCREATE TABLE sync_groups \(.*?\n\);\n\nCREATE TABLE sync_group_members \(.*?\n\);\n",
            "\n",
            schema,
            flags=re.DOTALL,
        )
        return schema.replace(
            "CREATE INDEX idx_sync_group_members_skill ON sync_group_members(skill_id);\n",
            "",
        )

    @staticmethod
    def _normalize_definition(definition: str | None) -> str:
        return re.sub(r"\s+", "", definition or "").lower()

    @classmethod
    def _schema_objects(
        cls, connection: sqlite3.Connection, expected_objects: set[str] | None = None
    ) -> dict[str, sqlite3.Row]:
        object_names = tuple(expected_objects or cls._expected_schema_objects())
        placeholders = ",".join("?" for _ in object_names)
        rows = connection.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name IN " f"({placeholders})",
            object_names,
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
            "sync_groups",
            "sync_group_members",
            "skill_fts",
        }

    @classmethod
    def _expected_schema_objects(cls) -> set[str]:
        return cls._expected_tables() | {
            "idx_skills_root_path",
            "idx_snapshots_skill",
            "idx_group_members_snapshot",
            "idx_evidence_group",
            "idx_sync_group_members_skill",
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
            "sync_groups": [
                "group_id",
                "name",
                "authority_skill_id",
                "policy",
                "baseline_revision",
                "status",
                "created_at",
                "updated_at",
            ],
            "sync_group_members": [
                "group_id",
                "skill_id",
                "role",
                "baseline_snapshot_id",
                "baseline_content_hash",
            ],
        }

    @classmethod
    def _expected_v4_schema_objects(cls) -> set[str]:
        return cls._expected_schema_objects() - {
            "sync_groups",
            "sync_group_members",
            "idx_sync_group_members_skill",
        }
