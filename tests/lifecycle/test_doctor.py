from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from skillcheck.lifecycle.doctor import CheckStatus, Doctor


def test_doctor_reports_all_required_categories(tmp_path: Path) -> None:
    context = SimpleNamespace(
        config_path=tmp_path / "missing.yaml",
        index_path=tmp_path / "missing.db",
        reports_path=tmp_path / "reports",
        targets_detected=False,
        reviewer_available=False,
        mcp_available=True,
    )
    report = Doctor(context).run(fix=False)
    assert {item.code for item in report.checks} >= {
        "runtime.version",
        "path.shadowing",
        "config.parse",
        "database.integrity",
        "reports.permissions",
        "targets.detect",
        "reviewers.detect",
        "mcp.handshake",
    }
    assert any(item.status is CheckStatus.WARNING for item in report.checks)


def test_doctor_plan_only_allows_whitelisted_hooks() -> None:
    context = SimpleNamespace(
        python_version=(3, 11, 0),
        path_shadowing=True,
        config_error=None,
        index_path=None,
        reports_path=None,
        targets_detected=True,
        reviewer_available=True,
        mcp_available=True,
    )
    doctor = Doctor(context)
    plan = doctor.plan(doctor.run())
    assert plan.actions == ["restore_launcher_path"]
    assert doctor.apply(plan) == []

