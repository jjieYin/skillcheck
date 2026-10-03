import sqlite3

import pytest

from skillcheck.catalog.database import CatalogDatabase, IncompatibleCatalogError


@pytest.fixture
def v4_catalog(tmp_path):
    path = tmp_path / "index.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(CatalogDatabase._v4_schema_sql())
        connection.execute(
            "INSERT INTO library_roots "
            "(root_id, path, provider, scope, created_at, updated_at) "
            "VALUES ('root-1', '/fixtures/skills', 'local', 'user', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO skills "
            "(skill_id, root_id, relative_path, status, created_at, updated_at) "
            "VALUES ('skill-1', 'root-1', 'example/SKILL.md', 'active', 'now', 'now')"
        )
    return path


def test_v4_catalog_migrates_to_v5_without_losing_skills(v4_catalog) -> None:
    database = CatalogDatabase(v4_catalog)

    database.initialize()

    assert database.schema_version() == 7
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sync_groups").fetchone()[0] == 0


def test_migration_rolls_back_when_v5_table_creation_fails(v4_catalog, monkeypatch) -> None:
    monkeypatch.setattr(
        "skillcheck.catalog.migrations.V4_TO_V5_SQL",
        "CREATE TABLE sync_groups(group_id TEXT); INVALID SQL",
    )

    with pytest.raises(IncompatibleCatalogError):
        CatalogDatabase(v4_catalog).initialize()

    with sqlite3.connect(v4_catalog) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "4"
        assert "sync_groups" not in _schema_object_names(connection)
        assert "sync_group_members" not in _schema_object_names(connection)
        assert "idx_sync_group_members_skill" not in _schema_object_names(connection)


def test_migration_rolls_back_when_v4_baseline_has_drifted(v4_catalog) -> None:
    with sqlite3.connect(v4_catalog) as connection:
        connection.execute("DROP INDEX idx_evidence_group")

    with pytest.raises(IncompatibleCatalogError):
        CatalogDatabase(v4_catalog).initialize()

    with sqlite3.connect(v4_catalog) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "4"
        assert "sync_groups" not in _schema_object_names(connection)
        assert "sync_group_members" not in _schema_object_names(connection)
        assert "idx_sync_group_members_skill" not in _schema_object_names(connection)


@pytest.fixture
def v5_catalog(tmp_path):
    path = tmp_path / "index-v5.db"
    schema = CatalogDatabase._v5_schema_sql()
    with sqlite3.connect(path) as connection:
        connection.executescript(schema)
        connection.execute(
            "INSERT INTO library_roots "
            "(root_id, path, provider, scope, created_at, updated_at) "
            "VALUES ('root-1', '/fixtures/skills', 'local', 'global', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO skills "
            "(skill_id, root_id, relative_path, status, created_at, updated_at) "
            "VALUES ('skill-1', 'root-1', 'example/SKILL.md', 'active', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO skill_snapshots "
            "(snapshot_id, skill_id, root_id, relative_path, name, content_hash, status, indexed_at) "
            "VALUES ('snapshot-1', 'skill-1', 'root-1', 'example/SKILL.md', 'Example', 'pkg-hash', 'active', 'now')"
        )
    return path


def test_v5_catalog_migrates_to_v6_and_initializes_instruction_hash(v5_catalog) -> None:
    database = CatalogDatabase(v5_catalog)

    database.initialize()

    assert database.schema_version() == 7
    with database.connect() as connection:
        row = connection.execute(
            "SELECT instruction_hash, license, compatibility, metadata_json, allowed_tools_json "
            "FROM skill_snapshots WHERE snapshot_id = 'snapshot-1'"
        ).fetchone()
    assert tuple(row) == ("pkg-hash", "", "", "{}", "[]")


def test_v6_to_v7_migration_adds_nullable_fingerprints_and_segment_vectors(tmp_path) -> None:
    path = tmp_path / "index-v6.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(CatalogDatabase._v5_schema_sql())
        connection.execute("ALTER TABLE skill_snapshots ADD COLUMN instruction_hash TEXT NOT NULL DEFAULT ''")
        connection.execute("ALTER TABLE skill_snapshots ADD COLUMN license TEXT NOT NULL DEFAULT ''")
        connection.execute("ALTER TABLE skill_snapshots ADD COLUMN compatibility TEXT NOT NULL DEFAULT ''")
        connection.execute("ALTER TABLE skill_snapshots ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        connection.execute("ALTER TABLE skill_snapshots ADD COLUMN allowed_tools_json TEXT NOT NULL DEFAULT '[]'")
        connection.execute("UPDATE schema_meta SET value = '6' WHERE key = 'schema_version'")

    database = CatalogDatabase(path)
    database.initialize()

    assert database.schema_version() == 7
    with database.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(skill_snapshots)")}
        assert {"behavior_hash", "execution_hash", "hash_algorithm_revision"} <= columns
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'segment_vectors'"
        ).fetchone() is not None


def test_v5_to_v6_migration_rolls_back_atomically(v5_catalog, monkeypatch) -> None:
    monkeypatch.setattr(
        "skillcheck.catalog.migrations.V5_TO_V6_SQL",
        "ALTER TABLE skill_snapshots ADD COLUMN instruction_hash TEXT; INVALID SQL",
    )

    with pytest.raises(IncompatibleCatalogError):
        CatalogDatabase(v5_catalog).initialize()

    with sqlite3.connect(v5_catalog) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "5"
        columns = [row[1] for row in connection.execute("PRAGMA table_info(skill_snapshots)")]
    assert "instruction_hash" not in columns


def _schema_object_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'virtual table')"
        )
    }
