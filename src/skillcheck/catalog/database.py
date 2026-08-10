from __future__ import annotations

import json
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
        except IncompatibleCatalogError:
            raise
        except sqlite3.DatabaseError as error:
            raise IncompatibleCatalogError(
                "Existing catalog is invalid; reinitialize it for v0.4."
            ) from error

    def _create_schema(self) -> None:
        schema = files("skillcheck.catalog").joinpath("schema.sql").read_text(encoding="utf-8")
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
