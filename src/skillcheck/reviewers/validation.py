"""Strict validation for Agent review JSON output."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from skillcheck.models.review import AgentDecision


class ValidatedAgentOutput(BaseModel):
    groups: list[AgentDecision] = Field(default_factory=list)


_SCHEMA_PATH = Path(__file__).with_name("schemas") / "agent-review.schema.json"


def validate_agent_output(raw: str | bytes | dict) -> ValidatedAgentOutput:
    try:
        payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except json.JSONDecodeError as exc:
        raise ValueError("Agent 输出不是有效 JSON") from exc
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        path = ".".join(str(item) for item in error.path)
        raise ValueError(f"Agent 输出 schema 校验失败（{path or 'root'}）：{error.message}")
    try:
        return ValidatedAgentOutput(
            groups=[AgentDecision.model_validate(item) for item in payload["groups"]]
        )
    except Exception as exc:
        raise ValueError(f"Agent 输出 decision 校验失败：{exc}") from exc

