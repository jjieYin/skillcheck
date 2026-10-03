"""Deterministic activation, procedure and constraint sections for Skills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from skillcheck.core.features import _normalize_text, activation_text, lexical_features
from skillcheck.models.skill import SkillRecord

EmbeddingChannel = Literal["activation", "procedure", "constraint"]
ConstraintPolarity = Literal["required", "forbidden", "allowed", "conditional"]


@dataclass(frozen=True)
class ConstraintClause:
    text: str
    polarity: ConstraintPolarity
    action_features: tuple[str, ...]


@dataclass(frozen=True)
class SkillSections:
    activation_text: str
    procedure_chunks: tuple[str, ...]
    constraint_clauses: tuple[ConstraintClause, ...]
    capability_tokens: tuple[str, ...]


_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_POLARITY_PATTERNS: tuple[tuple[ConstraintPolarity, tuple[str, ...]], ...] = (
    ("forbidden", ("must not", "mustn't", "do not", "never", "禁止", "不得", "不可")),
    ("required", ("must", "always", "required", "必须", "务必", "应当")),
    ("conditional", ("only if", "unless", "if", "如果", "仅当", "除非")),
    ("allowed", ("allowed", "may", "允许", "可以")),
)


def extract_skill_sections(skill: SkillRecord) -> SkillSections:
    capability_tokens = tuple(
        sorted(
            {
                f"{field}:{str(value).strip()}"
                for field, values in {
                    "allowed_tools": skill.allowed_tools,
                    "tools": skill.tools,
                    "permissions": skill.permissions,
                    "environments": skill.environments,
                    "inputs": skill.inputs,
                    "outputs": skill.outputs,
                }.items()
                for value in values
                if str(value).strip()
            },
            key=str.casefold,
        )
    )
    chunks = _procedure_chunks(skill.body)
    clauses = tuple(_constraint_clauses(chunks))
    return SkillSections(
        activation_text=activation_text(skill),
        procedure_chunks=chunks,
        constraint_clauses=clauses,
        capability_tokens=capability_tokens,
    )


def _procedure_chunks(body: str) -> tuple[str, ...]:
    normalized = str(body).replace("\r\n", "\n").replace("\r", "\n")
    chunks: list[str] = []
    current: list[str] = []
    in_fence = False
    fence_lines: list[str] = []

    def flush(lines: list[str]) -> None:
        text = _normalize_text([" ".join(lines)])
        if text:
            chunks.extend(_bounded_chunks(text))

    for line in normalized.split("\n"):
        if _FENCE.match(line):
            if in_fence:
                flush(fence_lines)
                fence_lines = []
                in_fence = False
            else:
                flush(current)
                current = []
                in_fence = True
            continue
        if in_fence:
            fence_lines.append(line)
            continue
        if not line.strip():
            flush(current)
            current = []
            continue
        if _HEADING.match(line) or _LIST_ITEM.match(line):
            flush(current)
            current = []
        current.append(line)
    if in_fence:
        flush(fence_lines)
    flush(current)
    return tuple(chunks)


def _bounded_chunks(text: str) -> list[str]:
    if len(text) <= 800:
        return [text]
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + 800)
        result.append(text[start:end])
        if end == len(text):
            break
        start = end - 100
    return result


def _constraint_clauses(chunks: tuple[str, ...]) -> list[ConstraintClause]:
    result: list[ConstraintClause] = []
    for chunk in chunks:
        for sentence in _SENTENCE_END.split(chunk):
            text = _normalize_text([sentence])
            if not text:
                continue
            polarity = _polarity(text)
            if polarity is None:
                continue
            action = text
            for _, phrases in _POLARITY_PATTERNS:
                for phrase in phrases:
                    if any("\u3400" <= character <= "\u9fff" for character in phrase):
                        action = action.replace(phrase.casefold(), " ")
                    else:
                        action = re.sub(
                            rf"\b{re.escape(phrase)}\b",
                            " ",
                            action,
                            flags=re.IGNORECASE,
                        )
            action_features = tuple(sorted(lexical_features(action).keys()))
            result.append(ConstraintClause(text=text, polarity=polarity, action_features=action_features))
    return result


def _polarity(text: str) -> ConstraintPolarity | None:
    lowered = text.casefold()
    for polarity, phrases in _POLARITY_PATTERNS:
        if any(phrase.casefold() in lowered for phrase in phrases):
            return polarity
    return None
