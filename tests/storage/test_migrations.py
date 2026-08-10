import sqlite3

import pytest

from skillcheck.storage.database import Database


def test_schema_one_database_migrates_to_two(tmp_path) -> None:
    db = Database(tmp_path / "index.db")
    db.migrate()
    assert db.schema_version() == 2
    tables = db.table_names()
    assert {
        "scan_runs",
        "governance_groups",
        "evidence",
        "agent_reviews",
        "reports",
        "installation_plans",
    } <= tables


def test_failed_migration_rolls_back(tmp_path, monkeypatch) -> None:
    db = Database(tmp_path / "index.db")
    monkeypatch.setattr(db, "migration_sql", lambda version: ("CREATE TABLE broken(",))
    with pytest.raises(sqlite3.Error):
        db.migrate()
    assert "broken" not in db.table_names()
