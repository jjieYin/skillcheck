from types import SimpleNamespace

from typer.testing import CliRunner

from skillcheck.app.main import app

runner = CliRunner()


class FakeAddPipeline:
    def __init__(self) -> None:
        self.executed = False
        self.config = SimpleNamespace(scan_paths=[], extra_paths=[])
        report = SimpleNamespace(decision=SimpleNamespace(value="PASS"), source_hash="sha256:test")
        plan = SimpleNamespace()
        self.prepared = SimpleNamespace(report=report, plan=plan, paths=None)

    def prepare(self, request):
        return self.prepared

    def execute(self, prepared):
        self.executed = True
        return []


def test_add_check_only_does_not_install(monkeypatch) -> None:
    pipeline = FakeAddPipeline()
    monkeypatch.setattr("skillcheck.commands.add.build_add_pipeline", lambda _: pipeline)
    result = runner.invoke(app, ["add", "source", "--check-only"])
    assert result.exit_code == 0
    assert pipeline.executed is False
