from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.pipelines.add_pipeline import AddResult, PreparedAdd

runner = CliRunner()


class FakeAddPipeline:
    def __init__(self, target: Path) -> None:
        self.target = target
        self.prepared = PreparedAdd(
            source="source",
            source_hash="sha256:test",
            review_state="local_only",
            targets=["codex"],
            target_paths=[target],
            files=["SKILL.md"],
        )
        self.executed = False

    def prepare(self, source, targets, target_paths):
        assert source == "source"
        assert targets == ["codex"]
        return self.prepared

    def execute(self, prepared, *, confirmed):
        assert prepared is self.prepared
        assert confirmed is True
        self.executed = True
        return AddResult(installed_paths=[self.target / "skill"], source_hash=prepared.source_hash)


def test_add_shows_preflight_then_installs_only_with_yes(monkeypatch, tmp_path: Path) -> None:
    pipeline = FakeAddPipeline(tmp_path / "installed")
    monkeypatch.setattr("skillcheck.commands.add.build_add_pipeline", lambda _: pipeline)
    monkeypatch.setattr("skillcheck.commands.add._target_root", lambda _target, _config: pipeline.target)

    result = runner.invoke(app, ["add", "source", "--yes"])

    assert result.exit_code == 0
    assert "sha256:test" in result.stdout
    assert "local_only" in result.stdout
    assert pipeline.executed is True


def test_add_has_no_legacy_review_or_check_only_options() -> None:
    assert runner.invoke(app, ["add", "source", "--review", "none"]).exit_code != 0
    assert runner.invoke(app, ["add", "source", "--check-only"]).exit_code != 0
