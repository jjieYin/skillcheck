from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.models import CheckReport, InstallationPlan


class AddRequest(BaseModel):
    source: str
    targets: list[str] = Field(default_factory=list)
    target_paths: list[Path] = Field(default_factory=list)
    review: str = "none"
    top_k: int | None = None
    confirmed: bool = False


@dataclass(frozen=True)
class PreparedAdd:
    report: CheckReport
    plan: InstallationPlan
    paths: Any = None


class AddPipeline:
    def __init__(
        self,
        *,
        checker,
        planner: InstallationPlanner,
        executor: InstallationExecutor,
    ) -> None:
        self.checker = checker
        self.planner = planner
        self.executor = executor

    def prepare(self, request: AddRequest) -> PreparedAdd:
        check_kwargs = {"use_llm": request.review != "none"}
        if request.top_k is not None:
            check_kwargs["top_k"] = request.top_k
        result = self.checker.check(request.source, **check_kwargs)
        plan = self.planner.create(
            result.report,
            targets=request.targets,
            target_paths=request.target_paths,
        )
        return PreparedAdd(report=result.report, plan=plan, paths=getattr(result, "paths", None))

    def execute(self, prepared: PreparedAdd) -> list[Path]:
        self.planner.validate(prepared.plan, approval_token=prepared.plan.approval_token)
        return self.executor.execute(prepared.report, prepared.plan)

    def run(self, request: AddRequest) -> PreparedAdd | list[Path]:
        prepared = self.prepare(request)
        if not request.confirmed:
            return prepared
        return self.execute(prepared)
