"""Deterministic registry for Agent target adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from skillcheck.targets.agents import AGENT_ORDER, EmptyTarget, normalize_agent
from skillcheck.targets.base import AgentId, AgentTarget, ConfigChange, DetectionResult
from skillcheck.targets.config_io import ConfigWriteResult


@dataclass(frozen=True)
class DiscoveryOutcome:
    detections: list[DetectionResult]
    preselected: list[str]


@dataclass(frozen=True)
class SetupPreview:
    scope: str
    changes: list[ConfigChange]


@dataclass(frozen=True)
class SetupResult:
    scope: str
    changed_files: list[Path]
    results: list[ConfigWriteResult]
    validations: list[bool]
    cancelled: bool = False


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

    def discovery_outcome(
        self,
        detections: list[DetectionResult],
        selected: list[str],
    ) -> DiscoveryOutcome:
        return DiscoveryOutcome(detections=detections, preselected=selected)

    def setup_preview(self, scope: str, changes: list[ConfigChange]) -> SetupPreview:
        return SetupPreview(scope=scope, changes=changes)

    def cancelled_result(self, preview: SetupPreview) -> SetupResult:
        return SetupResult(
            scope=preview.scope,
            changed_files=[],
            results=[],
            validations=[],
            cancelled=True,
        )

    def setup_result(
        self,
        results: list[ConfigWriteResult],
        validations: list[bool],
        *,
        scope: str = "global",
    ) -> SetupResult:
        return SetupResult(
            scope=scope,
            changed_files=[result.path for result in results if result.changed],
            results=results,
            validations=validations,
        )
