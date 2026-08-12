from __future__ import annotations

from types import SimpleNamespace

from skillcheck.targets.base import AgentId, DetectionResult
from skillcheck.ui.agent_picker import AgentPicker, build_picker_model


def detected(agent: str) -> DetectionResult:
    return DetectionResult(agent=AgentId(agent), cli_path=f"/usr/bin/{agent}")


def missing(agent: str) -> DetectionResult:
    return DetectionResult(agent=AgentId(agent))


def test_detected_and_configured_agents_are_preselected() -> None:
    model = build_picker_model(
        detections=[detected("codex"), detected("claude"), missing("cursor")],
        configured=["codex"],
    )
    assert [item.value for item in model if item.checked] == ["codex", "claude"]
    assert model[2].label.endswith("（未检测）")


def test_escape_returns_cancelled_without_selection() -> None:
    fake_prompt = SimpleNamespace(answer=None)
    result = AgentPicker(prompt=fake_prompt).choose([])
    assert result.cancelled is True
    assert result.selected == []


def test_checkbox_prompt_returns_only_available_agents() -> None:
    class Question:
        def ask(self):
            return ["codex", "cursor"]

    class Prompt:
        def checkbox(self, *_args, **_kwargs):
            return Question()

    result = AgentPicker(prompt=Prompt()).choose([detected("codex"), missing("cursor")])
    assert result.selected == ["codex"]
