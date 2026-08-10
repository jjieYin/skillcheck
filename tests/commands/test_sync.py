from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.models import SyncSummary

runner = CliRunner()


class _Pipeline:
    def __init__(self) -> None:
        self.paths = None

    def run(self, *, paths=None) -> SyncSummary:
        self.paths = paths
        return SyncSummary(revision="revision-1", added=1, updated=2, removed=3, invalid=4)


def test_sync_prints_incremental_summary(monkeypatch) -> None:
    pipeline = _Pipeline()
    monkeypatch.setattr("skillcheck.commands.sync.build_sync_pipeline", lambda _: pipeline)

    result = runner.invoke(app, ["sync", "changed/SKILL.md"])

    assert result.exit_code == 0
    assert "revision: revision-1" in result.stdout
    assert "added: 1" in result.stdout
    assert "updated: 2" in result.stdout
    assert "removed: 3" in result.stdout
    assert "invalid: 4" in result.stdout
    assert pipeline.paths == [Path("changed/SKILL.md")]


def test_sync_json_prints_the_summary_model(monkeypatch) -> None:
    pipeline = _Pipeline()
    monkeypatch.setattr("skillcheck.commands.sync.build_sync_pipeline", lambda _: pipeline)

    result = runner.invoke(app, ["sync", "--json"])

    assert result.exit_code == 0
    assert '"revision":"revision-1"' in result.stdout
