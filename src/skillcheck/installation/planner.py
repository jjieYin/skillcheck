from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from skillcheck.installation.manifest import plan_from_report
from skillcheck.models import CheckReport, InstallationPlan
from skillcheck.parser import content_hash
from skillcheck.sources import SourceLimits, stage_source


class InstallationPlanner:
    def __init__(self, *, staging_parent: Path | str | None = None, limits: SourceLimits | None = None) -> None:
        self.staging_parent = staging_parent
        self.limits = limits or SourceLimits()

    def create(self, report: CheckReport, *, targets: list[str], target_paths: list[Path]) -> InstallationPlan:
        return plan_from_report(report, targets=targets, target_paths=target_paths)

    @staticmethod
    def source_hash(root: Path) -> str:
        from skillcheck.parser import content_hash

        return content_hash(root)

    def create_controlled(
        self,
        *,
        source: str,
        source_hash: str,
        targets: list[str],
        target_paths: list[Path],
    ) -> InstallationPlan:
        now = datetime.now(UTC)
        return InstallationPlan(
            plan_id=f"plan-{uuid4().hex}",
            source=source,
            source_hash=source_hash,
            decision="PASS",
            targets=targets,
            target_paths=target_paths,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            approval_token=uuid4().hex,
        )

    def validate(self, plan: InstallationPlan, *, approval_token: str) -> None:
        from datetime import UTC, datetime

        if approval_token != plan.approval_token:
            raise ValueError("安装确认令牌无效")
        if datetime.now(UTC) >= plan.expires_at:
            raise ValueError("安装计划已过期")
        with stage_source(plan.source, limits=self.limits, staging_parent=self.staging_parent) as staged:
            actual_hash = content_hash(staged.root)
        if actual_hash != plan.source_hash:
            raise ValueError(f"来源已变化：expected {plan.source_hash}, got {actual_hash}")
