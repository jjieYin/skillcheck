from pathlib import Path

from skillcheck.audit import LibraryAuditor
from skillcheck.models import Finding, Severity
from tests.helpers import skill_record


def test_audit_analyzes_a_b_only_once() -> None:
    skills = [
        skill_record(skill_id="a", content_hash="sha256:a"),
        skill_record(skill_id="b", content_hash="sha256:b"),
    ]
    vectors = {"a": [1.0, 0.0], "b": [0.99, 0.01]}
    result = LibraryAuditor(top_k=5).audit(skills, vectors, findings=[])
    assert result.compared_pairs == [("a", "b")]


def test_identical_content_is_grouped_as_exact_duplicate() -> None:
    skills = [
        skill_record(skill_id="a", content_hash="sha256:same"),
        skill_record(skill_id="b", content_hash="sha256:same"),
    ]
    result = LibraryAuditor(top_k=5).audit(skills, {}, findings=[])
    assert len(result.groups) == 1
    assert result.groups[0].relation == "EXACT_DUPLICATE"
    assert result.groups[0].member_skill_ids == ["a", "b"]


def test_missing_vector_is_reported_without_aborting_other_pairs() -> None:
    skills = [
        skill_record(skill_id="a", content_hash="sha256:a"),
        skill_record(skill_id="b", content_hash="sha256:b"),
        skill_record(skill_id="c", content_hash="sha256:c"),
    ]
    result = LibraryAuditor(top_k=5).audit(
        skills,
        {"a": [1.0, 0.0], "b": [0.99, 0.01]},
        findings=[],
    )
    assert ("a", "b") in result.compared_pairs
    assert any(f.rule_id == "AUDIT001" and "c" in f.message for f in result.findings)


def test_path_filter_and_group_order_are_stable() -> None:
    skills = [
        skill_record(skill_id="z", root_path=Path("/skills/z"), content_hash="sha256:z"),
        skill_record(skill_id="a", root_path=Path("/skills/a"), content_hash="sha256:a"),
    ]
    vectors = {"z": [1.0, 0.0], "a": [0.99, 0.01]}
    first = LibraryAuditor(top_k=5).audit(skills, vectors, findings=[], root_path="/skills")
    second = LibraryAuditor(top_k=5).audit(skills, vectors, findings=[], root_path="/skills")
    assert first.groups == second.groups
    assert first.compared_pairs == [("a", "z")]


def test_single_security_finding_is_a_security_issue() -> None:
    result = LibraryAuditor().audit(
        [skill_record(skill_id="unsafe", content_hash="sha256:unsafe")],
        {},
        findings={
            "unsafe": [
                Finding(
                    rule_id="SEC002",
                    severity=Severity.HIGH,
                    message="Skill contains a hardcoded credential.",
                    remediation="Remove the credential.",
                )
            ]
        },
    )

    assert result.groups[0].relation == "SECURITY_ISSUE"
