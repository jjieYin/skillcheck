from skillcheck.llm import AuditGroupReviewInput, LLMReviewer, LLMReviewInput
from skillcheck.models import AuditGroup, Decision, Finding, Severity
from tests.helpers import skill_record


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls += 1
        self.prompts.append(f"{system}\n{user}")
        return next(self.responses)


def test_invalid_response_retries_once_then_falls_back() -> None:
    client = FakeClient(["not-json", "still-not-json"])
    review_input = LLMReviewInput(new_skill=skill_record(), candidates=[], findings=[])
    result = LLMReviewer(client).review(review_input)
    assert result.decision == Decision.MANUAL_REVIEW
    assert result.llm_used is False
    assert client.calls == 2


def test_valid_structured_response_is_accepted() -> None:
    client = FakeClient(['{"decision":"MERGE","confidence":"high","target_skill_id":"api-check","evidence":["same task"],"recommendations":["merge"]}'])
    result = LLMReviewer(client).review(LLMReviewInput(new_skill=skill_record(), candidates=[], findings=[]))
    assert result.decision == Decision.MERGE
    assert result.target_skill_id == "api-check"
    assert result.llm_used is True


def test_secret_content_is_redacted_from_prompt() -> None:
    secret_skill = skill_record(body="API_KEY='sk-test-1234567890'")
    finding = Finding(
        rule_id="SEC002",
        severity=Severity.HIGH,
        message="Hardcoded credential",
        remediation="Remove it",
    )
    client = FakeClient(['{"decision":"MANUAL_REVIEW","confidence":"low","evidence":[],"recommendations":[]}'])
    LLMReviewer(client).review(LLMReviewInput(new_skill=secret_skill, candidates=[], findings=[finding]))
    assert "sk-test-1234567890" not in client.prompts[0]
    assert "body omitted" in client.prompts[0]


def test_audit_group_review_uses_group_members() -> None:
    client = FakeClient(['{"decision":"DEPRECATE","confidence":"medium","target_skill_id":"b","evidence":["duplicate"],"recommendations":["disable b"]}'])
    group = AuditGroup(
        group_id="AG-high-overlap-1",
        relation="HIGH_OVERLAP",
        member_skill_ids=["a", "b"],
        confidence="medium",
    )
    result = LLMReviewer(client).review_audit_group(
        AuditGroupReviewInput(group=group, skills=[skill_record(skill_id="a"), skill_record(skill_id="b")], findings=[])
    )
    assert result.decision == Decision.DEPRECATE
    assert "a" in client.prompts[0] and "b" in client.prompts[0]
