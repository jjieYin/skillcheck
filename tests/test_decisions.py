from skillcheck.decisions import RuleDecisionEngine
from skillcheck.models import CandidateMatch, Decision, Finding, Severity
from tests.helpers import skill_record


def test_rule_decisions_cover_precedence_and_relationships() -> None:
    engine = RuleDecisionEngine()
    base = skill_record(content_hash="sha256:same")
    duplicate = CandidateMatch(
        skill=skill_record(skill_id="copy", content_hash="sha256:same"),
        similarity=1.0,
    )
    assert engine.decide(base, duplicate, []).decision == Decision.DUPLICATE

    variant = CandidateMatch(
        skill=skill_record(skill_id="prod", environments=["production"]),
        similarity=0.91,
    )
    assert engine.decide(skill_record(environments=["test"]), variant, []).decision == Decision.VARIANT

    conflict = CandidateMatch(
        skill=skill_record(skill_id="writer", permissions=["database-write"]),
        similarity=0.90,
    )
    assert engine.decide(skill_record(permissions=["database-read"]), conflict, []).decision == Decision.CONFLICT

    unsafe = Finding(
        rule_id="SEC002",
        severity=Severity.HIGH,
        message="Hardcoded credential",
        remediation="Remove the credential.",
    )
    assert engine.decide(base, duplicate, [unsafe]).decision == Decision.UNSAFE

    unrelated = CandidateMatch(skill=skill_record(skill_id="docs"), similarity=0.20)
    assert engine.decide(base, unrelated, []).decision == Decision.PASS


def test_similar_result_contains_actionable_evidence() -> None:
    result = RuleDecisionEngine().decide(
        skill_record(),
        CandidateMatch(skill=skill_record(skill_id="other"), similarity=0.9),
        [],
    )
    assert result.decision == Decision.SIMILAR
    assert result.evidence
    assert result.recommendations
