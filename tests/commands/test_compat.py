from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


class FakeScanPipeline:
    def __init__(self) -> None:
        self.called = False

    def run(self, scope, review):
        self.called = True
        return SimpleNamespace(
            skill_count=0,
            report=SimpleNamespace(markdown=Path("report.md"), json_path=Path("report.json")),
        )


class FakeAddPipeline:
    def __init__(self) -> None:
        self.install_called = False
        self.prepared = SimpleNamespace(
            report=SimpleNamespace(
                decision=SimpleNamespace(value="PASS",),
                confidence="high",
            ),
            paths=SimpleNamespace(markdown=Path("report.md"), json=Path("report.json")),
        )

    def prepare(self, request):
        return self.prepared

    def execute(self, prepared):
        self.install_called = True
        return []


def test_audit_forwards_to_scan_with_notice(monkeypatch) -> None:
    pipeline = FakeScanPipeline()
    monkeypatch.setattr("skillcheck.commands.compat.build_scan_pipeline", lambda _: pipeline)
    result = runner.invoke(app, ["audit", "--no-llm"])
    assert result.exit_code == 0
    assert "audit 已合并到 scan" in result.stdout
    assert pipeline.called is True


def test_check_forwards_to_add_check_only(monkeypatch) -> None:
    pipeline = FakeAddPipeline()
    monkeypatch.setattr("skillcheck.commands.compat.build_add_pipeline", lambda _: pipeline)
    result = runner.invoke(app, ["check", "sample"])
    assert result.exit_code == 0
    assert "请改用 skillcheck add sample --check-only" in result.stdout
    assert pipeline.install_called is False

