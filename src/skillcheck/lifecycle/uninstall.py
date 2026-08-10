"""Precise program uninstall that preserves user Skill data by default."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class UninstallPlan(BaseModel):
    remove_program: bool = True
    remove_agent_configs: bool = True
    remove_index: bool = False
    remove_reports: bool = False
    remove_user_config: bool = False
    exact_paths: list[str] = Field(default_factory=list)


class UninstallResult(BaseModel):
    changed: bool
    cancelled: bool = False
    message: str = ""
    removed_paths: list[str] = Field(default_factory=list)


class UninstallManager:
    def __init__(self, context: Any) -> None:
        self.context = context

    def plan(self) -> UninstallPlan:
        paths = list(self.context.layout.owned_program_paths())
        self._validate_paths(paths)
        return UninstallPlan(exact_paths=[str(path) for path in paths])

    def execute(self, plan: UninstallPlan, *, confirmed: bool):
        self._validate_paths(plan.exact_paths)
        if not confirmed:
            return self.context.results.cancelled()
        if plan.remove_agent_configs:
            for target in self.context.targets.configured():
                target.uninstall("configured")
        if plan.remove_program:
            self.context.helpers.remove_program_after_exit(plan.exact_paths)
        self.context.data.remove_selected(plan)
        return self.context.results.completed(plan)

    def _validate_paths(self, paths) -> None:
        roots = [Path.home().resolve(), Path.cwd().resolve()]
        owned_roots = [Path(item).expanduser().resolve() for item in self.context.layout.owned_roots()]
        for raw in paths:
            path = Path(raw).expanduser()
            if any(char in str(path) for char in "*?[]"):
                raise ValueError(f"卸载路径不允许通配符：{path}")
            resolved = path.resolve()
            if resolved in roots:
                raise ValueError(f"卸载路径过宽：{path}")
            if owned_roots and not any(resolved == root or root in resolved.parents for root in owned_roots):
                raise ValueError(f"卸载路径不属于 skillcheck 安装目录：{path}")

