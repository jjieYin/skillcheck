from __future__ import annotations

from pathlib import Path

from skillcheck.pipelines.setup_pipeline import SetupPipeline
from skillcheck.targets.base import AgentId, ConfigChange, DetectionResult
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.registry import TargetRegistry


class FakeStore:
    def __init__(self) -> None:
        self.calls = []

    def record_targets(self, scope, results, validations) -> None:
        self.calls.append((scope, results, validations))


class FakeTarget:
    def __init__(self, agent: AgentId, detected: bool = True) -> None:
        self.agent = agent
        self.detected = detected
        self.installs = 0

    def detect(self):
        return DetectionResult(agent=self.agent, cli_path=Path(f"{self.agent}.cmd") if self.detected else None)

    def preview(self, scope):
        return ConfigChange(
            agent=self.agent,
            path=Path(f"{self.agent}-{scope}.json"),
            after_text="{}",
            summary=["preview"],
        )

    def install(self, change):
        self.installs += 1
        return type("Result", (), {"changed": True, "path": change.path, "agent": self.agent})()

    def uninstall(self, scope):
        return None

    def validate(self, scope):
        return True


def test_setup_preselects_detected_agents() -> None:
    targets = {
        AgentId.CODEX: FakeTarget(AgentId.CODEX),
        AgentId.CLAUDE: FakeTarget(AgentId.CLAUDE),
        AgentId.CURSOR: FakeTarget(AgentId.CURSOR),
        AgentId.AGENTS: FakeTarget(AgentId.AGENTS, detected=False),
    }
    pipeline = SetupPipeline(TargetRegistry(targets), FakeStore())
    discovery = pipeline.discover()
    assert discovery.preselected == ["codex", "claude", "cursor"]


def test_setup_cancel_does_not_install() -> None:
    target = FakeTarget(AgentId.CODEX)
    store = FakeStore()
    pipeline = SetupPipeline(TargetRegistry([target]), store)
    preview = pipeline.preview(["codex"], scope="global")
    result = pipeline.apply(preview, confirmed=False)
    assert result.cancelled is True
    assert target.installs == 0
    assert store.calls == []


def test_setup_is_idempotent_with_real_codex_adapter(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    target = CodexTarget(config)
    pipeline = SetupPipeline(TargetRegistry([target]), FakeStore())
    first = pipeline.apply(pipeline.preview(["codex"], scope="global"), confirmed=True)
    second = pipeline.apply(pipeline.preview(["codex"], scope="global"), confirmed=True)
    assert first.changed_files == [config]
    assert second.changed_files == []
    assert config.read_text(encoding="utf-8").count("skillcheck") >= 1

