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


def test_existing_v4_catalog_with_matching_columns_but_missing_constraints_is_rejected(
    tmp_path,
) -> None:
    path = tmp_path / "index.db"
    expected_columns = CatalogDatabase._expected_columns()
    with sqlite3.connect(path) as connection:
        for table, columns in expected_columns.items():
            definition = ", ".join(f"{column} TEXT" for column in columns)
            connection.execute(f"CREATE TABLE {table} ({definition})")
        connection.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', '4')")
        connection.execute(
            "CREATE VIRTUAL TABLE skill_fts USING fts5("
            "snapshot_id UNINDEXED, name, description, body)"
        )

    with pytest.raises(IncompatibleCatalogError, match="reinitialize"):
        CatalogDatabase(path).initialize()


@pytest.mark.parametrize(
    "fts_definition",
    [
        "CREATE TABLE skill_fts (snapshot_id TEXT, name TEXT, description TEXT, body TEXT)",
        (
            "CREATE VIRTUAL TABLE skill_fts USING fts5("
            "snapshot_id UNINDEXED, name, description, body, extra)"
        ),
    ],
)
def test_existing_v4_catalog_with_invalid_fts_definition_is_rejected(tmp_path, fts_definition) -> None:
    database = CatalogDatabase(tmp_path / "index.db")
    database.initialize()
    with sqlite3.connect(database.path) as connection:
        connection.execute("DROP TABLE skill_fts")
        connection.execute(fts_definition)

    with pytest.raises(IncompatibleCatalogError, match="reinitialize"):
        database.initialize()


@pytest.mark.parametrize(
    ("index_name", "replacement"),
    [
        ("idx_evidence_group", None),
        ("idx_skills_root_path", "CREATE INDEX idx_skills_root_path ON skills(skill_id)"),
    ],
)
def test_existing_v4_catalog_with_missing_or_altered_index_is_rejected(
    tmp_path, index_name, replacement
) -> None:
    database = CatalogDatabase(tmp_path / "index.db")
    database.initialize()
    with sqlite3.connect(database.path) as connection:
        connection.execute(f"DROP INDEX {index_name}")
        if replacement:
            connection.execute(replacement)

    with pytest.raises(IncompatibleCatalogError, match="reinitialize"):
        database.initialize()
