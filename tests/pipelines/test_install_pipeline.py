from pathlib import Path

import pytest

from skillcheck.pipelines.install_pipeline import InstallPipeline
from skillcheck.targets.base import AgentId
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.cursor import CursorTarget
from skillcheck.targets.registry import TargetRegistry


def _target(agent: AgentId, root: Path):
    options = {
        "global_config": root / agent.value / "mcp.json",
        "project_config": root / "project" / agent.value / "mcp.json",
        "global_instructions": root / agent.value / "INSTRUCTIONS.md",
        "project_instructions": root / "project" / agent.value / "INSTRUCTIONS.md",
    }
    return CodexTarget(**options) if agent is AgentId.CODEX else CursorTarget(**options)


def test_preview_and_apply_configures_multiple_agents(tmp_path: Path) -> None:
    registry = TargetRegistry([
        _target(AgentId.CODEX, tmp_path),
        _target(AgentId.CURSOR, tmp_path),
    ])
    pipeline = InstallPipeline(registry, smoke_check=lambda: "smoke passed")

    preview = pipeline.preview(["codex", "cursor"], scope="global")
    result = pipeline.apply(preview, confirmed=True)

    assert preview.agents == ["codex", "cursor"]
    assert [change.kind for change in preview.changes] == ["mcp", "instructions"] * 2
    assert len(result.changed_files) == 4
    assert "smoke passed" in result.validations
    assert (tmp_path / "codex" / "INSTRUCTIONS.md").exists()
    assert (tmp_path / "cursor" / "INSTRUCTIONS.md").exists()


def test_cancel_does_not_write_any_file(tmp_path: Path) -> None:
    target = _target(AgentId.CODEX, tmp_path)
    pipeline = InstallPipeline(TargetRegistry([target]), smoke_check=lambda: "smoke passed")
    preview = pipeline.preview(["codex"], scope="global")

    result = pipeline.apply(preview, confirmed=False)

    assert result.changed_files == []
    assert result.validations == []
    assert not target.global_config.exists()
    assert not target.global_instructions.exists()


def test_apply_rolls_back_all_written_files_when_later_write_fails(tmp_path: Path, monkeypatch) -> None:
    target = _target(AgentId.CODEX, tmp_path)
    target.global_config.parent.mkdir(parents=True)
    target.global_config.write_text('existing = true\n', encoding="utf-8")
    pipeline = InstallPipeline(TargetRegistry([target]), smoke_check=lambda: "smoke passed")
    preview = pipeline.preview(["codex"], scope="global")
    original = target.global_config.read_text(encoding="utf-8")

    import skillcheck.pipelines.install_pipeline as module

    real_atomic_replace = module.atomic_replace
    writes = 0

    def fail_second(path, content, *, expected_hash):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("instruction write failed")
        return real_atomic_replace(path, content, expected_hash=expected_hash)

    monkeypatch.setattr(module, "atomic_replace", fail_second)

    with pytest.raises(OSError, match="instruction write failed"):
        pipeline.apply(preview, confirmed=True)

    assert target.global_config.read_text(encoding="utf-8") == original
    assert not target.global_instructions.exists()


def test_discover_exposes_instruction_paths(tmp_path: Path) -> None:
    target = _target(AgentId.CODEX, tmp_path)
    discovery = InstallPipeline(TargetRegistry([target]), smoke_check=lambda: "smoke passed").discover()

    assert discovery.agents[0].instruction_path == target.global_instructions


def test_smoke_failure_rolls_back_written_files(tmp_path: Path) -> None:
    target = _target(AgentId.CODEX, tmp_path)
    pipeline = InstallPipeline(
        TargetRegistry([target]),
        smoke_check=lambda: (_ for _ in ()).throw(RuntimeError("smoke failed")),
    )
    preview = pipeline.preview(["codex"], scope="global")

    with pytest.raises(RuntimeError, match="smoke failed"):
        pipeline.apply(preview, confirmed=True)

    assert not target.global_config.exists()
    assert not target.global_instructions.exists()
