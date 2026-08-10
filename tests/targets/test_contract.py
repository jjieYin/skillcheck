from dataclasses import FrozenInstanceError
from pathlib import Path

from pydantic import ValidationError

from skillcheck.targets.base import AgentId, ConfigChange, DetectionResult


def test_detection_and_change_models_are_immutable() -> None:
    detected = DetectionResult(agent=AgentId.CODEX, config_path=Path("config.toml"))
    change = ConfigChange(
        agent=AgentId.CODEX,
        path=Path("config.toml"),
        after_text="[mcp_servers.skillcheck]\n",
        summary=["add skillcheck server"],
    )
    assert detected.agent is AgentId.CODEX
    assert change.changed is True
    try:
        detected.agent = AgentId.CLAUDE
    except (ValidationError, FrozenInstanceError):
        pass
    else:
        raise AssertionError("DetectionResult must be immutable")
