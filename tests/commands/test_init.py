from pathlib import Path

from typer.testing import CliRunner

from skillcheck.app.main import app
from skillcheck.catalog.models import LibraryRoot, RootScope, SyncSummary
from skillcheck.pipelines.init_pipeline import InitPreview, InitResult

runner = CliRunner()


class FakeInitPipeline:
    def __init__(self, root: LibraryRoot) -> None:
        self.root = root
        self.applied: list[bool] = []

    def discover(self, extra_paths):
        return [self.root]

    def preview(self, roots):
        return InitPreview(roots=list(roots), database_path=Path("catalog.db"))

    def apply(self, preview, *, confirmed: bool):
        self.applied.append(confirmed)
        return InitResult(changed=confirmed, sync=SyncSummary(revision="initial", added=1))


def test_init_lists_roots_and_cancels_without_state_changes(monkeypatch, tmp_path: Path) -> None:
    root = LibraryRoot(
        root_id="root-1",
        path=tmp_path / "skills",
        provider="codex",
        scope=RootScope.GLOBAL,
    )
    pipeline = FakeInitPipeline(root)
    monkeypatch.setattr("skillcheck.commands.init.build_init_pipeline", lambda _: pipeline)

    result = runner.invoke(app, ["init"], input="n\n")

    assert result.exit_code == 0
    assert f"- codex global: {root.path}" in result.stdout
    assert "Cancelled" in result.stdout
    assert pipeline.applied == [False]


def test_init_yes_prints_first_sync_summary(monkeypatch, tmp_path: Path) -> None:
    root = LibraryRoot(
        root_id="root-1",
        path=tmp_path / "skills",
        provider="custom",
        scope=RootScope.CUSTOM,
    )
    pipeline = FakeInitPipeline(root)
    monkeypatch.setattr("skillcheck.commands.init.build_init_pipeline", lambda _: pipeline)

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 0
    assert "Initialized: added 1, updated 0, invalid 0" in result.stdout
    assert pipeline.applied == [True]
