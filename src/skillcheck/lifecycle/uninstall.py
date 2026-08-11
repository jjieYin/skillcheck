"""Remove only Skillcheck-owned integrations unless complete removal is requested."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class UninstallPlan(BaseModel):
    remove_program: bool = False
    remove_agent_configs: bool = True
    remove_index: bool = False
    remove_reports: bool = False
    remove_user_config: bool = False
    program_paths: list[str] = Field(default_factory=list)
    data_paths: list[str] = Field(default_factory=list)
    exact_paths: list[str] = Field(default_factory=list)


class UninstallResult(BaseModel):
    changed: bool
    cancelled: bool = False
    message: str = ""
    removed_paths: list[str] = Field(default_factory=list)


class UninstallManager:
    def __init__(self, context: Any) -> None:
        self.context = context

    def plan(self, *, keep_cli: bool = False, keep_data: bool = False, complete: bool = False) -> UninstallPlan:
        remove_program = complete and not keep_cli
        remove_data = complete and not keep_data
        program_paths = list(getattr(self.context.layout, "owned_program_paths", list)()) if remove_program else []
        data_paths = list(getattr(self.context.layout, "owned_data_paths", list)()) if remove_data else []
        if remove_data and not data_paths:
            data_paths = list(getattr(self.context.layout, "owned_data_roots", list)())
        paths = [*program_paths, *data_paths]
        self._validate_paths(paths)
        return UninstallPlan(
            remove_program=remove_program,
            remove_index=remove_data,
            remove_reports=remove_data,
            remove_user_config=remove_data,
            program_paths=[str(path) for path in program_paths],
            data_paths=[str(path) for path in data_paths],
            exact_paths=[str(path) for path in paths],
        )

    def execute(self, plan: UninstallPlan, *, confirmed: bool) -> UninstallResult:
        self._validate_paths(plan.exact_paths)
        if not confirmed:
            return UninstallResult(changed=False, cancelled=True, message="Cancelled; no files were changed.")
        changed = False
        removed_paths: list[str] = []
        scheduled_paths: list[str] = []
        scope = getattr(self.context, "agent_scope", "global")
        if plan.remove_agent_configs:
            for target in getattr(self.context, "targets", ()).configured():
                result = target.uninstall(scope)
                changed = bool(getattr(result, "changed", result)) or changed
                remove_markers = getattr(target, "uninstall_instructions", None)
                if callable(remove_markers):
                    marker = remove_markers(scope)
                    changed = bool(getattr(marker, "changed", marker)) or changed
        if plan.remove_program:
            result = self.context.helpers.remove_program_after_exit(plan.program_paths)
            changed = bool(getattr(result, "removed", result)) or changed
            removed_paths.extend(getattr(result, "removed", []))
            scheduled_paths.extend(getattr(result, "scheduled", []))
        if plan.remove_index or plan.remove_reports or plan.remove_user_config:
            data = getattr(self.context, "data", None)
            if data is not None:
                result = data.remove_selected(plan)
                changed = bool(getattr(result, "removed", result)) or changed
                removed_paths.extend(getattr(result, "removed", []))
                scheduled_paths.extend(getattr(result, "scheduled", []))
        message = "Skillcheck integrations removed."
        if scheduled_paths:
            message += " Some locked program files are scheduled for removal after Skillcheck exits."
            changed = True
        return UninstallResult(
            changed=changed,
            message=message,
            removed_paths=[*removed_paths, *scheduled_paths],
        )

    def _validate_paths(self, paths: list[str] | list[Path]) -> None:
        protected = [Path.home().resolve(), Path.cwd().resolve()]
        owned = [Path(item).expanduser().resolve() for item in getattr(self.context.layout, "owned_roots", list)()]
        if not owned or any(root in protected or root == Path(root.anchor) for root in owned):
            raise ValueError("uninstall owned locations are unsafe")
        for raw in paths:
            path = Path(raw).expanduser()
            if any(char in str(path) for char in "*?[]"):
                raise ValueError(f"uninstall path cannot contain wildcards: {path}")
            resolved = path.resolve()
            if resolved in protected or not any(resolved == root or root in resolved.parents for root in owned):
                raise ValueError(f"uninstall path is outside Skillcheck-owned locations: {path}")
