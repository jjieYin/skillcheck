from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from skillcheck.models import CheckReport, Decision
from skillcheck.parser import content_hash, parse_frontmatter
from skillcheck.sources import SourceLimits, stage_source


class InstallBlocked(RuntimeError):
    """Raised when an installation cannot safely proceed."""


class Installer:
    def __init__(self, limits: SourceLimits | None = None) -> None:
        self.limits = limits or SourceLimits()

    def install(
        self,
        report: CheckReport,
        *,
        target_root: Path | str,
        confirmed: bool = False,
        name: str | None = None,
    ) -> Path:
        self._check_decision(report, confirmed=confirmed, name=name)
        target_root = Path(target_root).expanduser().resolve()
        _validate_target_root(target_root)
        target_root.mkdir(parents=True, exist_ok=True)
        staged = stage_source(report.source, limits=self.limits, staging_parent=target_root.parent)
        try:
            actual_hash = content_hash(staged.root)
            if actual_hash != report.source_hash:
                raise InstallBlocked(
                    f"source hash changed since check: expected {report.source_hash}, got {actual_hash}"
                )
            skill_name = name or _skill_name(staged.root)
            _validate_name(skill_name)
            target = target_root / skill_name
            if target.exists():
                raise InstallBlocked(f"installation target already exists: {target}")
            temporary = target_root / f".{skill_name}.skillcheck-{uuid.uuid4().hex}"
            try:
                shutil.copytree(staged.root, temporary, symlinks=False)
                os.replace(temporary, target)
            except Exception:
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)
                raise
            return target
        finally:
            staged.close()

    @staticmethod
    def _check_decision(report: CheckReport, *, confirmed: bool, name: str | None) -> None:
        allowed = {Decision.PASS, Decision.APPROVE, Decision.VARIANT, Decision.MODIFY}
        if report.decision not in allowed:
            raise InstallBlocked(f"decision {report.decision.value} cannot be installed directly")
        if not confirmed:
            raise InstallBlocked("explicit confirmation is required")
        if report.decision in {Decision.VARIANT, Decision.MODIFY} and not name:
            raise InstallBlocked("variant or modified Skill requires an explicit target name")


def _skill_name(root: Path) -> str:
    marker = root / "SKILL.md"
    try:
        metadata, _ = parse_frontmatter(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        metadata = {}
    return str(metadata.get("name") or root.name).strip()


def _validate_name(name: str) -> None:
    if not name or name in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name):
        raise InstallBlocked("target Skill name contains unsupported path characters")


def _validate_target_root(path: Path) -> None:
    if path == Path(path.anchor) or path == Path.home().resolve() or path == Path.cwd().resolve():
        raise InstallBlocked(f"安装目标过宽，拒绝写入：{path}")
