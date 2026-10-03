"""Structured, pair-local signals used by relationship decisions."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from math import log
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skillcheck.models.skill import SkillRecord


@dataclass(frozen=True)
class PairSignalsV2:
    """Channel-specific evidence about one ordered pair of Skills."""

    semantic_similarity: float | None = None
    dense_similarity: float | None = None
    lexical_similarity: float | None = None
    capability_similarity: float | None = None
    permission_conflict: bool = False
    environment_variant: bool = False
    package_hash_equal: bool = False
    instruction_hash_equal: bool = False
    behavior_hash_equal: bool = False
    execution_present_left: bool = False
    execution_present_right: bool = False
    execution_hash_equal: bool | None = None
    execution_equivalent: bool = False
    activation_lexical_similarity: float | None = None
    procedure_coverage_left: float | None = None
    procedure_coverage_right: float | None = None
    constraint_action_similarity: float | None = None
    constraint_polarity_mismatch: bool = False
    hashed_lexical_similarity: float | None = None
    activation_dense_similarity: float | None = None
    procedure_dense_coverage_left: float | None = None
    procedure_dense_coverage_right: float | None = None
    permission_difference: bool = False
    relation_score: float | None = None
    semantic_model_calibrated: bool = True
    signals_version: str = "v2"


# Existing callers and historical JSON use the short name.  The v2 dataclass
# keeps every old field and gives all new fields defaults for old persisted runs.
PairSignals = PairSignalsV2


_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_LATIN_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_MARKDOWN_NOISE = re.compile(r"[`*_>#~\[\]{}()|:;]", re.UNICODE)


def activation_text(skill: SkillRecord) -> str:
    """Return normalized trigger/capability text without synthetic labels."""

    values: list[str] = [skill.name, skill.description]
    values.extend(skill.allowed_tools)
    values.extend(skill.tools)
    values.extend(skill.permissions)
    values.extend(skill.environments)
    return _normalize_text(values)


def procedure_text(skill: SkillRecord) -> str:
    """Return normalized procedural text without synthetic field labels."""

    values: list[str] = [skill.body]
    values.extend(skill.inputs)
    values.extend(skill.outputs)
    return _normalize_text(values)


def lexical_features(text: str) -> Counter[str]:
    """Extract stable Latin word/bigram and CJK 2–4 gram features."""

    normalized = _normalize_text([text])
    features: Counter[str] = Counter()
    for run in _CJK_RUN.findall(normalized):
        for size in range(2, min(4, len(run)) + 1):
            features.update(run[index : index + size] for index in range(len(run) - size + 1))

    latin_tokens: list[str] = []
    for token in _LATIN_TOKEN.findall(normalized):
        if any("\u3400" <= character <= "\u9fff" for character in token):
            continue
        token = token.casefold()
        if token:
            latin_tokens.append(token)
            features[token] += 1
    features.update(
        " ".join(pair)
        for pair in pairwise(latin_tokens)
        if pair[0] and pair[1]
    )
    return Counter({feature: min(count, 3) for feature, count in features.items()})


def idf_weights(documents: Iterable[Counter[str]]) -> dict[str, float]:
    """Compute corpus-local IDF weights for one lexical channel."""

    rows = list(documents)
    document_frequency: Counter[str] = Counter()
    for document in rows:
        document_frequency.update(document.keys())
    size = len(rows)
    return {
        feature: log((size + 1) / (frequency + 1)) + 1
        for feature, frequency in document_frequency.items()
    }


def weighted_counter_cosine(
    left: Counter[str], right: Counter[str], idf: dict[str, float]
) -> float:
    """Return cosine similarity after IDF weighting and per-document TF capping."""

    if not left or not right:
        return 0.0
    left_values = {key: min(value, 3) * idf.get(key, 1.0) for key, value in left.items()}
    right_values = {key: min(value, 3) * idf.get(key, 1.0) for key, value in right.items()}
    dot = sum(value * right_values.get(key, 0.0) for key, value in left_values.items())
    left_norm = sum(value * value for value in left_values.values()) ** 0.5
    right_norm = sum(value * value for value in right_values.values()) ** 0.5
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _normalize_text(values: Iterable[object]) -> str:
    text = " ".join(str(value) for value in values if value is not None and str(value).strip())
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _MARKDOWN_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()
