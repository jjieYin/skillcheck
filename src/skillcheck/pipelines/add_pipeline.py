from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from skillcheck.governance import GovernanceAnalyzer
from skillcheck.installation.executor import InstallationExecutor
from skillcheck.installation.planner import InstallationPlanner
from skillcheck.models import CheckReport, Decision, Finding
from skillcheck.sources import SourceSafetyError, stage_source


class PreparedAdd(BaseModel):
    """A read-only installation proposal tied to immutable source bytes."""

    source: str
    source_hash: str
    review_state: Literal["reviewed", "local_only", "stale"]
    targets: list[str]
    target_paths: list[Path]
    files: list[str]
    deterministic_blockers: list[Finding] = Field(default_factory=list)
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=15))


class AddResult(BaseModel):
    installed_paths: list[Path] = Field(default_factory=list)
    source_hash: str


class AddPipeline:
    """Preflight an untrusted source locally, then install only after confirmation."""

    def __init__(
        self,
        *,
        governance: GovernanceAnalyzer,
        planner: InstallationPlanner,
        executor: InstallationExecutor,
    ) -> None:
        self.governance = governance
        self.planner = planner
        self.executor = executor
        self.config = None

    def prepare(
        self, source: str, targets: list[str], target_paths: list[Path]
    ) -> PreparedAdd:
        source_hash, files = self._stage_details(source)
        preflight = self.governance.repository.latest_source_preflight(source_hash)
        if preflight is None:
            result = self.governance.analyze_source(source, limit=20)
            preflight = self.governance.repository.get_source_preflight(result.run_id)
        now = datetime.now(UTC)
        if preflight.expires_at <= now:
            review_state: Literal["reviewed", "local_only", "stale"] = "stale"
        elif self.governance.repository.has_agent_review(preflight.run_id):
            review_state = "reviewed"
        else:
            review_state = "local_only"
        return PreparedAdd(
            source=source,
            source_hash=source_hash,
            review_state=review_state,
            targets=list(targets),
            target_paths=[Path(item) for item in target_paths],
            files=files,
            deterministic_blockers=preflight.deterministic_blockers,
            expires_at=preflight.expires_at,
        )

    def execute(self, prepared: PreparedAdd, *, confirmed: bool) -> AddResult:
        if not confirmed:
            return AddResult(source_hash=prepared.source_hash)
        if prepared.expires_at <= datetime.now(UTC):
            raise ValueError("来源预检已过期，请重新执行 add")
        if prepared.deterministic_blockers:
            raise SourceSafetyError("确定性安全检查发现阻断项，拒绝安装")
        actual_hash, _files = self._stage_details(prepared.source)
        if actual_hash != prepared.source_hash:
            raise ValueError(f"来源已变化：expected {prepared.source_hash}, got {actual_hash}")
        plan = self.planner.create_controlled(
            source=prepared.source,
            source_hash=prepared.source_hash,
            targets=prepared.targets,
            target_paths=prepared.target_paths,
        )
        self.planner.validate(plan, approval_token=plan.approval_token)
        report = CheckReport(
            report_id=f"preflight-{uuid4().hex}",
            source=prepared.source,
            source_hash=prepared.source_hash,
            decision=Decision.PASS,
            confidence="local",
            blocking=False,
            findings=prepared.deterministic_blockers,
        )
        return AddResult(
            installed_paths=self.executor.execute(report, plan),
            source_hash=prepared.source_hash,
        )

    def run(
        self,
        source: str,
        *,
        targets: list[str],
        target_paths: list[Path],
        confirmed: bool,
    ) -> AddResult:
        prepared = self.prepare(source, targets, target_paths)
        return self.execute(prepared, confirmed=confirmed)

    def _stage_details(self, source: str) -> tuple[str, list[str]]:
        with stage_source(
            source,
            limits=self.planner.limits,
            staging_parent=self.planner.staging_parent,
        ) as staged:
            source_hash = self.planner.source_hash(staged.root)
            files = sorted(
                item.relative_to(staged.root).as_posix()
                for item in staged.root.rglob("*")
                if item.is_file() and ".git" not in item.parts
            )
        return source_hash, files
