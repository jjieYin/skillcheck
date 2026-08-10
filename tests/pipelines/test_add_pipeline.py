from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.models import Decision, InstallationPlan
from skillcheck.parser import content_hash
from skillcheck.pipelines.add_pipeline import AddPipeline, AddRequest
from tests.helpers import check_report, write_skill


def test_add_prepare_is_read_only_and_hash_bound(tmp_path: Path) -> None:
    source = write_skill(tmp_path / "source", name="new-skill", body="A safe skill body with enough detail.")
    report = check_report(Decision.PASS).model_copy(
        update={"source": str(source), "source_hash": content_hash(source)}
    )
    checker = SimpleNamespace(check=lambda source, use_llm: SimpleNamespace(report=report, paths=None))
    pipeline = AddPipeline(
        checker=checker,
        planner=InstallationPlanner(staging_parent=tmp_path / "staging"),
        executor=InstallationExecutor(),
    )
    prepared = pipeline.run(
        AddRequest(
            source=str(source),
            targets=["codex"],
            target_paths=[tmp_path / "installed"],
            confirmed=False,
        )
    )
    assert prepared.plan.source_hash == report.source_hash
    assert not (tmp_path / "installed").exists()

    (source / "SKILL.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="来源已变化"):
        pipeline.execute(prepared)


def test_multi_target_install_rolls_back_previous_target(tmp_path: Path) -> None:
    first = tmp_path / "first" / "skill"

    class FakeInstaller:
        def __init__(self) -> None:
            self.calls = 0

        def install(self, report, *, target_root, confirmed):
            self.calls += 1
            if self.calls == 1:
                first.parent.mkdir(parents=True)
                first.mkdir()
                return first
            raise RuntimeError("second target failed")

    removed: list[Path] = []

    class FakeRollback:
        def remove_created(self, paths):
            removed.extend(paths)

    executor = InstallationExecutor(FakeInstaller(), FakeRollback())
    plan = InstallationPlan(
        plan_id="plan-1",
        source="source",
        source_hash="hash",
        decision="PASS",
        targets=["codex", "claude"],
        target_paths=[tmp_path / "first", tmp_path / "second"],
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        approval_token="token",
    )
    with pytest.raises(RuntimeError, match="second target failed"):
        executor.execute(check_report(Decision.PASS), plan)
    assert removed == [first]
