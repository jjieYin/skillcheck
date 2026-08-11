from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
