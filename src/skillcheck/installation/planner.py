from __future__ import annotations

from pathlib import Path

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
