from __future__ import annotations

import subprocess
from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


def test_scan_is_local_only(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("scan must not start an Agent subprocess")

    result = SimpleNamespace(
        report=SimpleNamespace(markdown="report.md", json="report.json"),
        skill_count=2,
        json_payload=lambda: {
            "skill_count": 2,
            "report": {"markdown": "report.md", "json": "report.json"},
        },
    )
    pipeline = SimpleNamespace(run=lambda paths: result)
    monkeypatch.setattr("skillcheck.commands.scan.build_scan_pipeline", lambda _: pipeline)
    monkeypatch.setattr(subprocess, "run", forbidden)

    invocation = runner.invoke(app, ["scan", "--json"])

    assert invocation.exit_code == 0
    assert '"agent_reviews"' not in invocation.stdout
    assert "report.json" in invocation.stdout


def test_scan_accepts_only_path_json_and_config() -> None:
    result = runner.invoke(app, ["scan", "--review", "none"])

    assert result.exit_code != 0
