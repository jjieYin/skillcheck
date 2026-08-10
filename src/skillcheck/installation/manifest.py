from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from skillcheck.models import CheckReport, InstallationPlan


def source_hash(path: Path) -> str:
    marker = path / "SKILL.md"
    return "sha256:" + hashlib.sha256(marker.read_bytes()).hexdigest()


def approval_token() -> str:
    return secrets.token_urlsafe(24)


def plan_from_report(
    report: CheckReport,
    *,
    targets: list[str],
    target_paths: list[Path],
    ttl: timedelta = timedelta(minutes=15),
) -> InstallationPlan:
    now = datetime.now(UTC)
    return InstallationPlan(
        plan_id=f"plan-{now.strftime('%Y%m%d-%H%M%S-%f')}",
        source=report.source,
        source_hash=report.source_hash,
        decision=report.decision.value,
        targets=targets,
        target_paths=target_paths,
        created_at=now,
        expires_at=now + ttl,
        approval_token=approval_token(),
    )
