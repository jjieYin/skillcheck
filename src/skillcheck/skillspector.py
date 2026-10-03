from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from skillcheck.models import Finding, Severity


class SkillSpectorAdapter:
    """Optional adapter for NVIDIA SkillSpector's JSON terminal output."""

    def __init__(self, command: str = "skillspector", timeout_seconds: int = 30) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def scan(self, root: Path) -> list[Finding]:
        if not self.available():
            return [
                Finding(
                    rule_id="CAP001",
                    severity=Severity.INFO,
                    message="SkillSpector is unavailable; only built-in checks ran.",
                    evidence_path="SKILL.md",
                    remediation="Install SkillSpector and configure its command for an additional security scan.",
                )
            ]
        try:
            result = subprocess.run(
                [self.command, "scan", str(root), "--format", "json"],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
            payload = json.loads(result.stdout or "[]")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            error_kind = type(exc).__name__
            return [
                Finding(
                    rule_id="CAP002",
                    severity=Severity.MEDIUM,
                    message=f"SkillSpector scan failed ({error_kind}).",
                    evidence_path="SKILL.md",
                    remediation="Review the scanner installation and rerun the scan.",
                )
            ]
        return _findings_from_payload(payload)


def _findings_from_payload(payload) -> list[Finding]:
    if isinstance(payload, dict):
        payload = payload.get("findings", payload.get("results", []))
    if not isinstance(payload, list):
        return []
    findings: list[Finding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "medium")).lower()
        try:
            level = Severity(severity)
        except ValueError:
            level = Severity.MEDIUM
        findings.append(
            Finding(
                rule_id=str(item.get("rule_id", item.get("rule", "SPC001"))),
                severity=level,
                message=str(item.get("message", "SkillSpector finding")),
                evidence_path=str(item.get("evidence_path", item.get("path", "SKILL.md"))),
                remediation=str(item.get("remediation", "Review the SkillSpector finding.")),
            )
        )
    return findings
