from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app


runner = CliRunner()


class FakeSetupPipeline:
    def __init__(self) -> None:
        self.applied = []

    def discover(self):
        return SimpleNamespace(
            detections=[SimpleNamespace(agent=SimpleNamespace(value="codex"), cli_path=Path("codex"), config_path=None)],
            preselected=["codex"],
        )

    def preview(self, agents, *, scope):
        return SimpleNamespace(
            changes=[
                SimpleNamespace(
                    agent=SimpleNamespace(value="codex"),
                    path=Path("config.toml"),
                    changed=True,
                    summary=["add"],
                )
            ],
            scope=scope,
        )

    def apply(self, preview, *, confirmed):
        self.applied.append(confirmed)
        return SimpleNamespace(changed_files=[], validations=[True], cancelled=not confirmed)


def test_setup_yes_applies_preview(monkeypatch) -> None:
    pipeline = FakeSetupPipeline()
    monkeypatch.setattr("skillcheck.commands.setup.build_setup_pipeline", lambda _: pipeline)
    result = runner.invoke(app, ["setup", "--yes", "--no-interactive"])
    assert result.exit_code == 0
    assert pipeline.applied == [True]
    assert "配置已是最新" in result.stdout


def test_setup_without_confirmation_does_not_write(monkeypatch) -> None:
    pipeline = FakeSetupPipeline()
    monkeypatch.setattr("skillcheck.commands.setup.build_setup_pipeline", lambda _: pipeline)
    result = runner.invoke(app, ["setup", "--no-interactive"])
    assert result.exit_code == 0
    assert pipeline.applied == [False]
    assert "已取消" in result.stdout

