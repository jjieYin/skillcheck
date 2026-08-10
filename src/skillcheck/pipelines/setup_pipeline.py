"""Detect, preview and apply Agent integration configuration changes."""

from __future__ import annotations

from typing import Protocol

from skillcheck.targets.registry import DiscoveryOutcome, SetupPreview, SetupResult, TargetRegistry


class TargetConfigStore(Protocol):
    def record_targets(self, scope: str, results, validations) -> None: ...


class SetupPipeline:
    def __init__(self, registry: TargetRegistry, config_store: TargetConfigStore) -> None:
        self.registry = registry
        self.config_store = config_store

    def discover(self) -> DiscoveryOutcome:
        detections = self.registry.detect_all()
        selected = [
            item.agent.value
            for item in detections
            if item.cli_path is not None or item.config_path is not None
        ]
        return self.registry.discovery_outcome(detections, selected)

    def preview(self, agents: list[str], *, scope: str) -> SetupPreview:
        changes = [self.registry.get(agent).preview(scope) for agent in agents]
        return self.registry.setup_preview(scope, changes)

    def apply(self, preview: SetupPreview, *, confirmed: bool) -> SetupResult:
        if not confirmed:
            return self.registry.cancelled_result(preview)
        results = []
        try:
            for change in preview.changes:
                results.append(self.registry.get(change.agent).install(change))
        except Exception:
            # A failed later target must not leave a partial setup behind.
            for result in reversed(results):
                if result.changed:
                    try:
                        self.registry.get(result.agent).uninstall(preview.scope)
                    except Exception:
                        pass
            raise
        validations = [
            bool(self.registry.get(change.agent).validate(preview.scope))
            for change in preview.changes
        ]
        self.config_store.record_targets(preview.scope, results, validations)
        return self.registry.setup_result(results, validations, scope=preview.scope)

