from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from skillcheck.models import (
    AuditGroup,
    CandidateMatch,
    Decision,
    Finding,
    ReviewAdvice,
    SkillRecord,
)


class LLMClient(Protocol):
    def complete(self, *, system: str, user: str) -> str:
        ...


class LLMReviewInput(BaseModel):
    new_skill: SkillRecord
    candidates: list[CandidateMatch] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class AuditGroupReviewInput(BaseModel):
    group: AuditGroup
    skills: list[SkillRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class _LLMOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: Decision
    confidence: str = "medium"
    target_skill_id: str | None = None
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    @field_validator("decision")
    @classmethod
    def decision_must_be_governance_action(cls, value: Decision) -> Decision:
        allowed = {
            Decision.APPROVE,
            Decision.MODIFY,
            Decision.MERGE,
            Decision.VARIANT,
            Decision.DEPRECATE,
            Decision.REJECT,
            Decision.MANUAL_REVIEW,
        }
        if value not in allowed:
            raise ValueError("LLM decision is not an allowed governance action")
        return value


class OpenAICompatibleClient:
    """Lazy OpenAI-compatible chat client for OpenAI, Qwen, or a proxy."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for remote LLM review") from exc
        if base_url:
            self._client = OpenAI(api_key=api_key, timeout=timeout, base_url=base_url)
        else:
            self._client = OpenAI(api_key=api_key, timeout=timeout)

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


class LLMReviewer:
    def __init__(self, client: LLMClient, *, max_attempts: int = 2) -> None:
        self.client = client
        self.max_attempts = max(1, max_attempts)

    def review(self, review_input: LLMReviewInput) -> ReviewAdvice:
        system = _system_prompt()
        user = _new_skill_prompt(review_input)
        return self._run(system, user)

    def review_audit_group(self, review_input: AuditGroupReviewInput) -> ReviewAdvice:
        system = _system_prompt()
        user = _audit_group_prompt(review_input)
        return self._run(system, user)

    def _run(self, system: str, user: str) -> ReviewAdvice:
        last_error = "no response"
        for attempt in range(self.max_attempts):
            try:
                raw = self.client.complete(
                    system=system,
                    user=user if attempt == 0 else f"{user}\n上一次输出无效，请只返回符合 schema 的 JSON。",
                )
                output = _LLMOutput.model_validate_json(raw)
                return ReviewAdvice(
                    decision=output.decision,
                    confidence=output.confidence,
                    target_skill_id=output.target_skill_id,
                    evidence=output.evidence,
                    recommendations=output.recommendations,
                    llm_used=True,
                )
            except (ValidationError, ValueError, TypeError, RuntimeError) as exc:
                last_error = type(exc).__name__
        return ReviewAdvice(
            decision=Decision.MANUAL_REVIEW,
            confidence="low",
            evidence=[f"LLM structured review failed: {last_error}"],
            recommendations=["人工复核候选 Skill 和安全检查结果；模型输出未被采纳。"],
            llm_used=False,
        )


def _system_prompt() -> str:
    return (
        "你是个人 Skill 库治理复核器。只输出 JSON，不要输出 Markdown。"
        "decision 只能是 APPROVE、MODIFY、MERGE、VARIANT、DEPRECATE、REJECT、MANUAL_REVIEW。"
        "必须基于提供的结构化证据，不能臆造不存在的能力。"
    )


def _new_skill_prompt(review_input: LLMReviewInput) -> str:
    payload = {
        "new_skill": _safe_skill_payload(review_input.new_skill, review_input.findings),
        "candidates": [
            {
                "skill_id": candidate.skill.skill_id,
                "similarity": candidate.similarity,
                "name": candidate.skill.name,
                "description": candidate.skill.description,
                "same_points": candidate.same_points,
                "different_points": candidate.different_points,
            }
            for candidate in review_input.candidates
        ],
        "findings": [finding.model_dump(mode="json") for finding in review_input.findings],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _audit_group_prompt(review_input: AuditGroupReviewInput) -> str:
    payload = {
        "group": review_input.group.model_dump(mode="json"),
        "skills": [_safe_skill_payload(skill, review_input.findings) for skill in review_input.skills],
        "findings": [finding.model_dump(mode="json") for finding in review_input.findings],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _safe_skill_payload(skill: SkillRecord, findings: list[Finding]) -> dict[str, object]:
    has_secret = any(finding.rule_id in {"SEC002", "SEC003"} for finding in findings)
    body = "[body omitted due to security finding]" if has_secret else _redact_secrets(skill.body[:4_000])
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "tools": skill.tools,
        "permissions": skill.permissions,
        "environments": skill.environments,
        "inputs": skill.inputs,
        "outputs": skill.outputs,
        "body": body,
    }


def _redact_secrets(text: str) -> str:
    return re.sub(
        r"(?:sk-[A-Za-z0-9_-]{10,}|(?:api[_-]?key|token|secret)\s*=\s*['\"][^'\"]+['\"])",
        "[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
