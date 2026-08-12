"""CodeGraph-style checkbox selection for Agent integrations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from skillcheck.targets.agents import AGENT_ORDER
from skillcheck.targets.base import AgentId, DetectionResult


@dataclass(frozen=True)
class PickerItem:
    value: str
    label: str
    checked: bool
    available: bool


@dataclass(frozen=True)
class PickerResult:
    selected: list[str]
    cancelled: bool = False


def _agent_value(value: Any) -> str:
    return str(value.value if isinstance(value, AgentId) else value).casefold()


def _is_available(detection: DetectionResult) -> bool:
    return bool(
        detection.cli_path
        or detection.config_path
        or detection.instruction_path
        or detection.skill_paths
        or detection.mcp_configured
        or detection.instructions_configured
    )


def build_picker_model(
    detections: Iterable[DetectionResult],
    configured: Iterable[str] = (),
    *,
    selection_initialized: bool = False,
) -> list[PickerItem]:
    """Build stable checkbox rows without touching files or terminal state."""
    by_agent = {_agent_value(item.agent): item for item in detections}
    configured_values = {_agent_value(item) for item in configured}
    model: list[PickerItem] = []
    for agent in AGENT_ORDER:
        value = agent.value
        detection = by_agent.get(value)
        available = detection is not None and _is_available(detection)
        label = value.title()
        if not available:
            label += "（未检测）"
        model.append(
            PickerItem(
                value=value,
                label=label,
                checked=available
                and (
                    value in configured_values
                    if selection_initialized
                    else detection is not None
                ),
                available=available,
            )
        )
    return model


class AgentPicker:
    """Render a checkbox prompt while keeping the decision injectable in tests."""

    def __init__(self, prompt: Any | None = None) -> None:
        self.prompt = prompt

    def choose(
        self,
        detections: Iterable[DetectionResult],
        configured: Iterable[str] = (),
        *,
        selection_initialized: bool = False,
    ) -> PickerResult:
        model = build_picker_model(
            detections,
            configured,
            selection_initialized=selection_initialized,
        )
        prompt = self.prompt
        if prompt is None:
            try:
                import questionary
            except ImportError as error:  # pragma: no cover - packaging failure path
                raise RuntimeError("Agent picker requires questionary; reinstall Skillcheck") from error
            prompt = questionary

        # Small fake prompts can expose an answer directly, which keeps tests
        # independent from terminal escape sequences.
        if hasattr(prompt, "answer") and not hasattr(prompt, "checkbox"):
            answer = prompt.answer
        else:
            choices = [
                _questionary_choice(prompt, item)
                for item in model
            ]
            question = prompt.checkbox(
                "Which agents should Skillcheck configure? (↑↓, Space, Enter, Esc)",
                choices=choices,
            )
            answer = question.ask() if hasattr(question, "ask") else question
        if answer is None:
            return PickerResult(selected=[], cancelled=True)
        selected = [str(item.value if hasattr(item, "value") else item).casefold() for item in answer]
        allowed = {item.value for item in model if item.available}
        return PickerResult(selected=[item for item in selected if item in allowed])


def _questionary_choice(prompt: Any, item: PickerItem) -> Any:
    choice_type = getattr(prompt, "Choice", None)
    if choice_type is None:
        try:
            import questionary

            choice_type = questionary.Choice
        except ImportError:
            return item.value
    return choice_type(title=item.label, value=item.value, checked=item.checked)
