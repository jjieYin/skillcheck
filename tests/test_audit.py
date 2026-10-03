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


def test_mismatched_vector_dimensions_are_reported_explicitly() -> None:
    skills = [
        skill_record(skill_id="a", content_hash="sha256:a"),
        skill_record(skill_id="b", content_hash="sha256:b"),
    ]

    result = LibraryAuditor(top_k=5).audit(
        skills,
        {"a": [1.0, 0.0], "b": [1.0]},
        findings=[],
    )

    assert any(f.rule_id == "AUDIT002" and "dimension" in f.message for f in result.findings)


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


def test_skill_security_finding_is_reported_without_creating_a_pair_group() -> None:
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

    assert not result.groups
    assert any(item.rule_id == "SEC002" for item in result.findings)


def test_skill_finding_does_not_change_a_semantic_pair_relation() -> None:
    skills = [
        skill_record(skill_id="unsafe", content_hash="sha256:unsafe"),
        skill_record(skill_id="normal", content_hash="sha256:normal"),
    ]
    finding = Finding(
        rule_id="SEC002",
        severity=Severity.HIGH,
        message="Skill contains a hardcoded credential.",
        remediation="Remove the credential.",
    )
    result = LibraryAuditor().audit(
        skills,
        {"unsafe": [1.0, 0.0], "normal": [0.99, 0.01]},
        findings={"unsafe": [finding], "normal": []},
    )

    assert [group.relation for group in result.groups] == ["HIGH_OVERLAP_CANDIDATE"]
    assert any(item.rule_id == "SEC002" for item in result.findings)
