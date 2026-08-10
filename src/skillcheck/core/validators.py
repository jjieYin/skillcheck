from __future__ import annotations

import re
from pathlib import Path

from skillcheck.models import Finding, Severity, SkillRecord
from skillcheck.core.parser import parse_frontmatter


class BuiltinValidator:
    """Small deterministic validator that works without a model or network."""

    def scan(self, root: Path, skill: SkillRecord) -> list[Finding]:
        findings: list[Finding] = []
        skill_file = root / "SKILL.md"
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            text = skill.body
        try:
            metadata, _ = parse_frontmatter(text)
        except ValueError:
            metadata = {}
        if not metadata.get("name"):
            findings.append(
                _finding("FMT001", Severity.MEDIUM, "Skill is missing a name.", "Add a stable name to frontmatter.")
            )
        if not metadata.get("description"):
            findings.append(
                _finding(
                    "FMT002",
                    Severity.MEDIUM,
                    "Skill is missing a description.",
                    "Describe the task boundary and expected output in frontmatter.",
                )
            )
        if len(skill.body.strip()) < 20:
            findings.append(
                _finding(
                    "QLT001",
                    Severity.LOW,
                    "Skill body is too short to explain a reliable procedure.",
                    "Add prerequisites, steps, limits, and expected output.",
                )
            )

        all_text = _read_safe_text(root)
        findings.extend(_security_findings(all_text))
        return findings


def _security_findings(text: str) -> list[Finding]:
    findings: list[Finding] = []
    if re.search(r"(?:subprocess\.|os\.system\s*\(|shell\s*=\s*True|bash\s+-c|powershell\s+-enc)", text, re.IGNORECASE):
        findings.append(
            _finding(
                "SEC001",
                Severity.HIGH,
                "Skill contains shell or process execution instructions.",
                "Document the exact command, constrain arguments, and avoid shell interpolation.",
            )
        )
    if re.search(r"(?:sk-[A-Za-z0-9_-]{10,}|(?:api[_-]?key|token|secret)\s*=\s*['\"][^'\"]+['\"])", text, re.IGNORECASE):
        findings.append(
            _finding(
                "SEC002",
                Severity.HIGH,
                "Skill appears to contain a hardcoded credential.",
                "Remove the value and read secrets from a secure runtime secret store.",
            )
        )
    if any(0x200B <= ord(character) <= 0x200F or 0x202A <= ord(character) <= 0x202E or 0x2066 <= ord(character) <= 0x2069 for character in text):
        findings.append(
            _finding(
                "SEC003",
                Severity.MEDIUM,
                "Skill contains hidden or bidirectional Unicode characters.",
                "Remove invisible controls and review the affected line manually.",
            )
        )
    if re.search(r"(?:curl|wget)\s+[^\n|]+\|\s*(?:sh|bash|zsh|powershell)", text, re.IGNORECASE):
        findings.append(
            _finding(
                "SEC004",
                Severity.CRITICAL,
                "Skill downloads remote content and pipes it directly to a shell.",
                "Download to a controlled file, verify its checksum, and review before execution.",
            )
        )
    if re.search(r"(?:\.\.[/\\]|file://|/etc/|[A-Za-z]:[/\\])", text, re.IGNORECASE):
        findings.append(
            _finding(
                "SEC005",
                Severity.MEDIUM,
                "Skill references a path outside its package or a host-absolute path.",
                "Use paths relative to the Skill root and explicitly document permitted locations.",
            )
        )
    return findings


def _read_safe_text(root: Path) -> str:
    chunks: list[str] = []
    root_resolved = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file() or ".git" in path.parts:
            continue
        try:
            if not path.resolve().is_relative_to(root_resolved):
                continue
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def _finding(rule_id: str, severity: Severity, message: str, remediation: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        message=message,
        evidence_path="SKILL.md",
        remediation=remediation,
    )
