from pathlib import Path

from skillcheck.targets.agents import resolve_executable
from skillcheck.targets.base import AgentId, DetectionResult
from skillcheck.targets.registry import TargetRegistry


class FakeTarget:
    def __init__(self, agent: AgentId) -> None:
        self.agent = agent

    def detect(self) -> DetectionResult:
        return DetectionResult(agent=self.agent, config_path=Path(f"{self.agent}.json"))


def test_registry_detects_all_targets_in_fixed_order() -> None:
    targets = {agent: FakeTarget(agent) for agent in reversed(tuple(AgentId))}
    results = TargetRegistry(targets).detect_all()
    assert [result.agent for result in results] == [
        AgentId.CODEX,
        AgentId.CLAUDE,
        AgentId.CURSOR,
        AgentId.AGENTS,
    ]


def test_registry_accepts_target_iterable() -> None:
    targets = [FakeTarget(agent) for agent in (AgentId.CURSOR, AgentId.CODEX)]
    assert [result.agent for result in TargetRegistry(targets).detect_all()] == [
        AgentId.CODEX,
        AgentId.CURSOR,
    ]


def test_windows_detection_prefers_cmd_over_ps1(tmp_path) -> None:
    (tmp_path / "codex.ps1").write_text("", encoding="utf-8")
    (tmp_path / "codex.cmd").write_text("", encoding="utf-8")
    result = resolve_executable("codex", search_path=[tmp_path], windows=True)
    assert result is not None
    assert result.name == "codex.cmd"
