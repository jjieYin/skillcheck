from __future__ import annotations

import re
from pathlib import Path

from skillcheck.core.parser import parse_frontmatter
from skillcheck.models import Finding, Severity, SkillRecord


class BuiltinValidator:
    """Small deterministic validator that works without a model or network."""

    def scan(self, root: Path, skill: SkillRecord) -> list[Finding]:
        findings: list[Finding] = []
        skill_file = root / "SKILL.md"
        try:
            text = skill_file.read_text(encoding="utf-8")
            has_source_frontmatter = True
        except (OSError, UnicodeError):
            text = skill.body
            has_source_frontmatter = False
        try:
            metadata, body = parse_frontmatter(text)
        except ValueError:
            metadata, body = {}, skill.body
        if (has_source_frontmatter and not metadata.get("name")) or (
            not has_source_frontmatter and not skill.name
        ):
            findings.append(
                _finding("FMT001", Severity.MEDIUM, "Skill is missing a name.", "Add a stable name to frontmatter.")
            )
        if (has_source_frontmatter and not metadata.get("description")) or (
            not has_source_frontmatter and not skill.description
        ):
            findings.append(
                _finding(
                    "FMT002",
                    Severity.MEDIUM,
                    "Skill is missing a description.",
                    "Describe the task boundary and expected output in frontmatter.",
                )
            )
        if has_source_frontmatter and metadata.get("name"):
            name = str(metadata["name"]).strip()
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
                findings.append(
                    _finding(
                        "FMT003",
                        Severity.MEDIUM,
                        "Skill name must be 1-64 lowercase letters, digits, or hyphens.",
                        "Use a stable lowercase hyphenated name.",
                    )
                )
            if name != root.name:
                findings.append(
                    _finding(
                        "FMT004",
                        Severity.MEDIUM,
                        "Skill name does not match its directory name.",
                        "Rename the directory or update the frontmatter name.",
                    )
                )
        description = metadata.get("description")
        if has_source_frontmatter and description is not None and len(str(description)) > 1024:
            findings.append(
                _finding(
                    "FMT005",
                    Severity.MEDIUM,
                    "Skill description exceeds 1024 characters.",
                    "Shorten the description to the task boundary and expected output.",
                )
            )
        allowed_tools = metadata.get("allowed-tools")
        if has_source_frontmatter and allowed_tools is not None and not _valid_allowed_tools(allowed_tools):
            findings.append(
                _finding(
                    "FMT006",
                    Severity.MEDIUM,
                    "allowed-tools must be a string or a list of strings.",
                    "Use a comma-separated string or a YAML list of tool names.",
                )
            )
        if len(body.strip()) < 20:
            findings.append(
                _finding(
                    "QLT001",
                    Severity.LOW,
                    "Skill body is too short to explain a reliable procedure.",
                    "Add prerequisites, steps, limits, and expected output.",
                )
            )
        if len(body.splitlines()) > 500:
            findings.append(
                _finding(
                    "QLT002",
                    Severity.LOW,
                    "Skill body exceeds 500 lines.",
                    "Split long procedures into focused Skills or reference documents.",
                )
            )

        all_text = _read_safe_text(root) or skill.body
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


def _valid_allowed_tools(value: object) -> bool:
    return isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    )
