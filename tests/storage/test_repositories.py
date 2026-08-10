from datetime import UTC, datetime

from skillcheck.models.report import ScanRun
from skillcheck.storage.database import Database
from skillcheck.storage.repositories import RunRepository, TableRepository


def test_run_repository_round_trip(tmp_path) -> None:
    db = Database(tmp_path / "index.db")
    db.migrate()
    repository = RunRepository(db)
    run = ScanRun(
        run_id="run-001",
        started_at=datetime.now(UTC),
        scopes=["D:/skills"],
        index_revision="rev-1",
        capabilities=["hash"],
        skill_count=2,
        finding_count=1,
        status="completed",
    )
    repository.save(run)
    restored = repository.get("run-001")
    assert restored is not None
    assert restored.scopes == ["D:/skills"]
    assert restored.status == "completed"


def test_table_repository_restricts_dynamic_table_names(tmp_path) -> None:
    db = Database(tmp_path / "index.db")
    db.migrate()
    repository = TableRepository(db)
    assert repository.count("scan_runs") == 0
    try:
        repository.count("skills; DROP TABLE skills")
    except ValueError as exc:
        assert "不允许查询表" in str(exc)
    else:
        raise AssertionError("未阻止非法表名")
