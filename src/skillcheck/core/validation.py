"""Composable built-in and optional external Skill validation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from skillcheck.models import Finding, SkillRecord


class ExternalValidator(Protocol):
    def scan(self, root: Path) -> list[Finding]:
        ...


class CompositeSkillValidator:
    """Run built-in rules for every Skill and optionally merge external rules."""

    def __init__(self, builtin, external: ExternalValidator | None = None) -> None:
        self.builtin = builtin
        self.external = external

    def scan(self, root: Path, skill: SkillRecord) -> list[Finding]:
        findings: list[Finding] = list(self.builtin.scan(root, skill))
        if self.external is not None:
            findings.extend(self.external.scan(root))
        return _dedupe(findings)


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str | None, str]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.rule_id, finding.evidence_path, finding.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result
