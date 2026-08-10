import sqlite3

import pytest

from skillcheck.catalog.database import CatalogDatabase, IncompatibleCatalogError

EXPECTED_TABLES = {
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


def test_initialize_creates_complete_v4_schema(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "index.db")

    database.initialize()

    assert database.schema_version() == 4
    assert EXPECTED_TABLES <= database.table_names()
    with sqlite3.connect(database.path) as connection:
        columns = connection.execute("PRAGMA table_info(skill_fts)").fetchall()
    assert [column[1] for column in columns] == ["snapshot_id", "name", "description", "body"]


def test_existing_v4_catalog_can_be_reopened(tmp_path) -> None:
    database = CatalogDatabase(tmp_path / "index.db")
    database.initialize()

    database.initialize()

    assert database.schema_version() == 4


def test_incompatible_existing_database_is_rejected_without_overwrite(tmp_path) -> None:
    path = tmp_path / "index.db"
    original = b"not-a-v4-database"
    path.write_bytes(original)

    with pytest.raises(IncompatibleCatalogError, match="reinitialize"):
        CatalogDatabase(path).initialize()

    assert path.read_bytes() == original


def test_existing_v4_catalog_with_placeholder_tables_is_rejected(tmp_path) -> None:
    path = tmp_path / "index.db"
    with sqlite3.connect(path) as connection:
        for table in EXPECTED_TABLES:
            if table == "schema_meta":
                connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', '4')")
            else:
                connection.execute(f"CREATE TABLE {table} (placeholder TEXT)")

    with pytest.raises(IncompatibleCatalogError, match="reinitialize"):
        CatalogDatabase(path).initialize()
