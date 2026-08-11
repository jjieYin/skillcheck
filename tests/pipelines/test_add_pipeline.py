from __future__ import annotations

from pathlib import Path

import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.governance import GovernanceAnalyzer
from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.pipelines.add_pipeline import AddPipeline
from skillcheck.sources import SourceSafetyError
from tests.helpers import write_skill


@pytest.fixture
def pipeline(tmp_path: Path) -> AddPipeline:
    database = CatalogDatabase(tmp_path / "state" / "catalog.db")
    database.initialize()
    catalog = CatalogRepository(database)
    return AddPipeline(
        governance=GovernanceAnalyzer(catalog, staging_root=tmp_path / "state" / "staging"),
        planner=InstallationPlanner(staging_parent=tmp_path / "state" / "staging"),
        executor=InstallationExecutor(),
    )


def test_add_rejects_changed_source_after_agent_review(pipeline: AddPipeline, tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="new-skill", body="A safe skill body with enough detail.")
    prepared = pipeline.prepare(str(source), ["codex"], [tmp_path / "installed"])
    (source / "SKILL.md").write_text("---\nname: new-skill\n---\nChanged body.", encoding="utf-8")

    with pytest.raises(ValueError, match="来源已变化"):
        pipeline.execute(prepared, confirmed=True)


def test_add_rejects_preflight_created_for_changed_source(
    pipeline: AddPipeline, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_skill(tmp_path / "source", name="new-skill", body="Original safe body.")
    analyze_source = pipeline.governance.analyze_source

    def change_before_preflight(path: str, *, limit: int):
        (source / "SKILL.md").write_text(
            "---\nname: new-skill\n---\nChanged before preflight.", encoding="utf-8"
        )
        return analyze_source(path, limit=limit)

    monkeypatch.setattr(pipeline.governance, "analyze_source", change_before_preflight)

    with pytest.raises(ValueError, match="预检结果与当前来源不一致"):
        pipeline.prepare(str(source), ["codex"], [tmp_path / "installed"])


def test_add_without_confirmation_writes_nothing(pipeline: AddPipeline, tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="new-skill", body="A safe skill body with enough detail.")

    result = pipeline.run(
        str(source),
        targets=["codex"],
        target_paths=[tmp_path / "installed"],
        confirmed=False,
    )

    assert result.installed_paths == []
    assert not (tmp_path / "installed").exists()


def test_add_executes_only_after_explicit_confirmation(pipeline: AddPipeline, tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="new-skill", body="A safe skill body with enough detail.")
    prepared = pipeline.prepare(str(source), ["codex"], [tmp_path / "installed"])

    result = pipeline.execute(prepared, confirmed=True)

    assert result.source_hash == prepared.source_hash
    assert result.installed_paths == [tmp_path / "installed" / "new-skill"]


def test_add_blocks_deterministic_security_findings(pipeline: AddPipeline, tmp_path: Path) -> None:
    source = write_skill(
        tmp_path / "unsafe",
        name="unsafe-skill",
        body="Never put credentials here: sk-abcdefghijklmnop.",
    )
    prepared = pipeline.prepare(str(source), ["codex"], [tmp_path / "installed"])

    assert prepared.deterministic_blockers
    with pytest.raises(SourceSafetyError, match="确定性安全检查"):
        pipeline.execute(prepared, confirmed=True)
