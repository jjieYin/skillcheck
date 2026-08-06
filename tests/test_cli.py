import json
from pathlib import Path

from typer.testing import CliRunner

from skillcheck.cli import app
from skillcheck.models import Decision
from skillcheck.reports import ReportWriter
from tests.helpers import check_report

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "skillcheck 0.1.0" in result.stdout


def test_cli_init_scan_check_and_report_json(tmp_path: Path) -> None:
    init = runner.invoke(app, ["init", "--home", str(tmp_path)])
    assert init.exit_code == 0
    config = tmp_path / ".skillcheck" / "config.yaml"

    scan = runner.invoke(app, ["scan", "--config", str(config), "--cwd", str(tmp_path), "--json"])
    assert scan.exit_code == 0
    assert json.loads(scan.stdout)["installation_count"] == 0

    fixture = Path("tests/fixtures/duplicate-a").resolve()
    check = runner.invoke(
        app,
        ["check", str(fixture), "--config", str(config), "--no-llm", "--json"],
    )
    assert check.exit_code == 0
    payload = json.loads(check.stdout)
    assert payload["decision"] == "PASS"

    latest = runner.invoke(app, ["report", "latest", "--config", str(config), "--json"])
    assert latest.exit_code == 0
    report_payload = json.loads(latest.stdout)
    shown = runner.invoke(
        app,
        ["report", "show", report_payload["report_id"], "--config", str(config), "--json"],
    )
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["report_id"] == report_payload["report_id"]


def test_cli_audit_and_install_blocked_report(tmp_path: Path) -> None:
    init = runner.invoke(app, ["init", "--home", str(tmp_path)])
    assert init.exit_code == 0
    config = tmp_path / ".skillcheck" / "config.yaml"
    report = check_report(Decision.MERGE)
    ReportWriter(tmp_path / ".skillcheck" / "reports").write(report)
    install = runner.invoke(
        app,
        [
            "install",
            report.report_id,
            "--target",
            "codex",
            "--yes",
            "--config",
            str(config),
        ],
    )
    assert install.exit_code == 2
    assert "安装已阻断" in install.output
