from pathlib import Path

from skillcheck.models import CheckReport, Decision, SkillRecord


def write_skill(root: Path, name: str = "sample", body: str = "Do the task safely.") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return root


def skill_record(**overrides) -> SkillRecord:
    values = {
        "skill_id": "api-check",
        "name": "api-check",
        "description": "Check an API",
        "root_path": Path("/fixtures/api-check"),
        "body": "Check an API endpoint safely.",
        "content_hash": "sha256:abc",
        "tools": ["http-client"],
        "permissions": ["network-read"],
        "environments": ["test"],
    }
    values.update(overrides)
    return SkillRecord(**values)


def check_report(decision: Decision = Decision.MERGE) -> CheckReport:
    return CheckReport(
        report_id="SC-20260806-000000-deadbeef",
        source="tests/fixtures/basic",
        source_hash="sha256:abc",
        decision=decision,
        confidence="high",
        blocking=decision in {Decision.REJECT, Decision.UNSAFE},
        findings=[],
        candidates=[],
        recommendations=["Review the existing Skill."],
        capabilities=["builtin-validator", "fake-embedding"],
    )
