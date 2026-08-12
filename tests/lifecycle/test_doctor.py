from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.lifecycle.doctor import REQUIRED_CODES, Doctor


def test_doctor_reports_exact_v4_checks(tmp_path: Path) -> None:
    context = SimpleNamespace(
        python_version=(3, 11, 0), path_shadowing=False, config=SimpleNamespace(schema_version=4, catalog=SimpleNamespace(initialized=False)),
        index_path=tmp_path / "index.db", reports_path=tmp_path, registry=None, mcp_available=True,
    )
    report = Doctor(context).run()

    assert tuple(item.code for item in report.checks) == REQUIRED_CODES


def test_doctor_fix_only_calls_owned_integration_or_empty_catalog_hooks(tmp_path: Path) -> None:
    calls: list[str] = []
    context = SimpleNamespace(
        python_version=(3, 11, 0), path_shadowing=False, config=SimpleNamespace(schema_version=4, catalog=SimpleNamespace(initialized=False)),
        index_path=tmp_path / "index.db", reports_path=tmp_path, registry=None, mcp_available=False,
        rewrite_skillcheck_integration=lambda: calls.append("integration"), initialize_empty_catalog=lambda: calls.append("catalog"),
    )
    doctor = Doctor(context)

    completed = doctor.apply(doctor.plan(doctor.run()))

    assert completed == ["rewrite_skillcheck_integration", "initialize_empty_catalog"]
    assert calls == ["integration", "catalog"]


def test_doctor_does_not_mutate_an_empty_catalog_during_diagnostics(tmp_path: Path) -> None:
    index = tmp_path / "index.db"
    index.touch()
    before = index.read_bytes()
    context = SimpleNamespace(
        python_version=(3, 11, 0), path_shadowing=False,
        config=SimpleNamespace(schema_version=4, catalog=SimpleNamespace(initialized=False)),
        index_path=index, reports_path=tmp_path, registry=None, mcp_available=True,
    )

    Doctor(context).run()

    assert index.read_bytes() == before


def test_doctor_rejects_schema_marker_without_complete_v4_catalog(tmp_path: Path) -> None:
    index = tmp_path / "index.db"
    import sqlite3

    with sqlite3.connect(index) as connection:
        connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '4')")
    before = index.read_bytes()
    context = SimpleNamespace(
        python_version=(3, 11, 0),
        path_shadowing=False,
        config=SimpleNamespace(schema_version=4, catalog=SimpleNamespace(initialized=True)),
        index_path=index,
        reports_path=tmp_path,
        registry=None,
        mcp_available=True,
    )

    report = Doctor(context).run()

    integrity = next(item for item in report.checks if item.code == "catalog.integrity")
    assert integrity.status.value == "error"
    assert index.read_bytes() == before


def test_doctor_accepts_complete_v5_catalog(tmp_path: Path) -> None:
    index = tmp_path / "index.db"
    CatalogDatabase(index).initialize()
    context = SimpleNamespace(
        python_version=(3, 11, 0),
        path_shadowing=False,
        config=SimpleNamespace(schema_version=4, catalog=SimpleNamespace(initialized=True)),
        index_path=index,
        reports_path=tmp_path,
        registry=None,
        mcp_available=True,
    )

    report = Doctor(context).run()

    integrity = next(item for item in report.checks if item.code == "catalog.integrity")
    assert integrity.status.value == "ok"


def test_doctor_reports_catalog_sync_warning_with_a_failure_message(tmp_path: Path) -> None:
    context = SimpleNamespace(
        python_version=(3, 11, 0),
        path_shadowing=False,
        config=SimpleNamespace(schema_version=4, catalog=SimpleNamespace(initialized=False)),
        index_path=tmp_path / "index.db",
        reports_path=tmp_path,
        registry=None,
        mcp_available=True,
        catalog_sync_warning="unreadable root",
    )

    report = Doctor(context).run()

    sync = next(item for item in report.checks if item.code == "catalog.sync")
    assert sync.status.value == "warning"
    assert sync.message == "Catalog sync warning: unreadable root"
