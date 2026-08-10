"""Deterministic registry for Agent target adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from skillcheck.targets.agents import AGENT_ORDER, EmptyTarget, normalize_agent
from skillcheck.targets.base import AgentId, AgentTarget, DetectionResult


class TargetRegistry:
    """Register and detect targets in a stable user-facing order."""

    def __init__(self, targets: Mapping[AgentId | str, AgentTarget] | Iterable[AgentTarget] | None = None) -> None:
        self._targets: dict[AgentId, AgentTarget] = {}
        if targets is None:
            targets = [EmptyTarget(agent) for agent in AGENT_ORDER]
        if isinstance(targets, Mapping):
            for agent, target in targets.items():
                self.register(agent, target)
        else:
            for target in targets:
                self.register(getattr(target, "agent"), target)

    def register(self, agent: AgentId | str, target: AgentTarget) -> None:
        normalized = normalize_agent(agent)
        self._targets[normalized] = target

    def get(self, agent: AgentId | str) -> AgentTarget:
        return self._targets[normalize_agent(agent)]

    def detect_all(self) -> list[DetectionResult]:
        results: list[DetectionResult] = []
        for agent in AGENT_ORDER:
            target = self._targets.get(agent)
            if target is not None:
                result = target.detect()
                results.append(result if isinstance(result, DetectionResult) else DetectionResult.model_validate(result))
        return results

    def __iter__(self):
        for agent in AGENT_ORDER:
            target = self._targets.get(agent)
            if target is not None:
                yield target
