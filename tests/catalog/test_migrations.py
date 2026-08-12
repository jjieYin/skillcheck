import sqlite3

import pytest

from skillcheck.catalog.database import CatalogDatabase, IncompatibleCatalogError


@pytest.fixture
def v4_catalog(tmp_path):
    path = tmp_path / "index.db"
    database = CatalogDatabase(path)
    database.initialize()
    with database.connect() as connection:
        connection.execute("DROP INDEX IF EXISTS idx_sync_group_members_skill")
        connection.execute("DROP TABLE IF EXISTS sync_group_members")
        connection.execute("DROP TABLE IF EXISTS sync_groups")
        connection.execute(
            "UPDATE schema_meta SET value = '4' WHERE key = 'schema_version'"
        )
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

    assert database.schema_version() == 5
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
