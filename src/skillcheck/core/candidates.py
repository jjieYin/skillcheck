"""Deterministic, channel-aware candidate retrieval for Skill governance."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import sqrt
from typing import Literal

import numpy as np

from skillcheck.core.features import (
    PairSignals,
    activation_text,
    idf_weights,
    lexical_features,
    weighted_counter_cosine,
)
from skillcheck.core.fingerprints import EMPTY_EXECUTION_HASH
from skillcheck.core.retrieval import cosine_similarity
from skillcheck.core.sections import SkillSections, extract_skill_sections
from skillcheck.models import SkillRecord


@dataclass(frozen=True)
class ChannelThresholdProfile:
    """Independent gates used for retrieval evidence, not one universal score."""

    activation_lexical: float = 0.55
    procedure_chunk: float = 0.50
    constraint_action: float = 0.55
    procedure_high_coverage: float = 0.66
    procedure_low_coverage: float = 0.34
    dense: float = 0.75
    semantic_calibrated: bool = False


class MultiChannelCandidateRetriever:
    """Union behavior/execution/hash channels and optional semantic channels."""

    def __init__(
        self,
        top_k: int = 5,
        thresholds: ChannelThresholdProfile | None = None,
    ) -> None:
        self.top_k = max(1, int(top_k))
        self.thresholds = thresholds or ChannelThresholdProfile()

    def retrieve(
        self,
        skills: Iterable[SkillRecord],
        sections: Mapping[str, SkillSections] | None = None,
        channel_vectors=None,
        vectorizer_kind: Literal["lexical_hash", "semantic"] = "lexical_hash",
    ) -> dict[tuple[str, str], PairSignals]:
        selected = sorted(skills, key=lambda skill: skill.skill_id)
        by_id = {skill.skill_id: skill for skill in selected}
        section_map = {
            skill.skill_id: (sections or {}).get(skill.skill_id, extract_skill_sections(skill))
            for skill in selected
        }
        pairs: set[tuple[str, str]] = set()
        pairs.update(_equal_hash_pairs(selected, "behavior_hash"))
        pairs.update(_execution_pairs(selected))

        activation_docs = {
            skill_id: lexical_features(section_map[skill_id].activation_text)
            for skill_id in by_id
        }
        procedure_docs = {
            skill_id: [lexical_features(chunk) for chunk in section_map[skill_id].procedure_chunks]
            for skill_id in by_id
        }
        constraint_docs = {
            skill_id: [
                lexical_features(" ".join(clause.action_features) or clause.text)
                for clause in section_map[skill_id].constraint_clauses
            ]
            for skill_id in by_id
        }
        activation_idf = idf_weights(activation_docs.values())
        procedure_idf = idf_weights(
            document for documents in procedure_docs.values() for document in documents
        )
        constraint_idf = idf_weights(
            document for documents in constraint_docs.values() for document in documents
        )

        activation_values: dict[tuple[str, str], float] = {}
        procedure_values: dict[tuple[str, str], tuple[float | None, float | None]] = {}
        constraint_values: dict[tuple[str, str], tuple[float | None, bool]] = {}
        for index, left in enumerate(selected):
            for right in selected[index + 1 :]:
                pair = (left.skill_id, right.skill_id)
                activation_score = weighted_counter_cosine(
                    activation_docs[left.skill_id], activation_docs[right.skill_id], activation_idf
                )
                if activation_score > 0:
                    activation_values[pair] = activation_score

        # Procedure/constraint matching is the expensive segment stage.  Use
        # the activation top-k union, fingerprint candidates and shared
        # constraint terms as its bounded input rather than comparing every
        # document pair quadratically.
        activation_pairs = _top_k_pairs(
            activation_values,
            self.top_k,
            # Keep a small recall cushion below the relation gate without
            # running expensive segment comparisons for boilerplate-level
            # activation matches.
            minimum=max(0.25, self.thresholds.activation_lexical - 0.15),
        )
        procedure_pairs = set(pairs) | activation_pairs
        constraint_pairs = procedure_pairs | _top_k_pairs(
            _shared_feature_scores(constraint_docs),
            self.top_k,
            minimum=1,
        )
        for pair in sorted(procedure_pairs):
            left, right = by_id[pair[0]], by_id[pair[1]]
            left_coverage, right_coverage = _procedure_coverage(
                procedure_docs[left.skill_id],
                procedure_docs[right.skill_id],
                procedure_idf,
                self.thresholds.procedure_chunk,
            )
            if left_coverage is not None or right_coverage is not None:
                procedure_values[pair] = (left_coverage, right_coverage)
        for pair in sorted(constraint_pairs):
            left, right = by_id[pair[0]], by_id[pair[1]]
            constraint_score, polarity_mismatch = _constraint_similarity(
                section_map[left.skill_id],
                section_map[right.skill_id],
                constraint_docs,
                left.skill_id,
                right.skill_id,
                constraint_idf,
            )
            if constraint_score is not None:
                constraint_values[pair] = (constraint_score, polarity_mismatch)
        pairs.update(
            _top_k_pairs(
                activation_values,
                self.top_k,
                minimum=self.thresholds.activation_lexical,
            )
        )
        pairs.update(
            _top_k_pairs(
                {pair: max(values) for pair, values in procedure_values.items()},
                self.top_k,
                minimum=self.thresholds.procedure_chunk,
            )
        )
        pairs.update(
            _top_k_pairs(
                {
                    pair: score
                    for pair, (score, _mismatch) in constraint_values.items()
                    if score is not None
                },
                self.top_k,
                minimum=self.thresholds.constraint_action,
            )
        )

        dense_values = (
            _dense_channel_values(
                selected,
                channel_vectors,
                self.top_k,
                self.thresholds.dense,
                vectorizer_kind,
            )
            if vectorizer_kind == "semantic"
            else {}
        )
        pairs.update(dense_values)
        result: dict[tuple[str, str], PairSignals] = {}
        for pair in sorted(pairs):
            left, right = by_id[pair[0]], by_id[pair[1]]
            activation_score = activation_values.get(pair)
            left_coverage, right_coverage = procedure_values.get(pair, (None, None))
            constraint_score, polarity_mismatch = constraint_values.get(pair, (None, False))
            dense = dense_values.get(pair)
            semantic = dense[0] if dense is not None and dense[4] == "semantic" else None
            hashed_dense = dense[0] if dense is not None and dense[4] == "lexical_hash" else None
            activation_dense = dense[1] if dense is not None and dense[4] == "semantic" else None
            procedure_dense_left = dense[2] if dense is not None and dense[4] == "semantic" else None
            procedure_dense_right = dense[3] if dense is not None and dense[4] == "semantic" else None
            result[pair] = PairSignals(
                semantic_similarity=semantic,
                dense_similarity=semantic,
                lexical_similarity=activation_score,
                capability_similarity=capability_similarity(left, right),
                permission_conflict=_permission_conflict(left.permissions, right.permissions),
                environment_variant=_environment_variant(left.environments, right.environments),
                package_hash_equal=left.content_hash == right.content_hash,
                instruction_hash_equal=left.instruction_hash == right.instruction_hash
                and bool(left.instruction_hash),
                behavior_hash_equal=bool(left.behavior_hash and left.behavior_hash == right.behavior_hash),
                execution_present_left=bool(left.execution_hash and left.execution_hash != EMPTY_EXECUTION_HASH),
                execution_present_right=bool(right.execution_hash and right.execution_hash != EMPTY_EXECUTION_HASH),
                execution_hash_equal=(
                    left.execution_hash == right.execution_hash
                    if left.execution_hash and right.execution_hash
                    else None
                ),
                execution_equivalent=_execution_equivalent(left, right),
                activation_lexical_similarity=activation_score,
                procedure_coverage_left=left_coverage,
                procedure_coverage_right=right_coverage,
                constraint_action_similarity=constraint_score,
                constraint_polarity_mismatch=polarity_mismatch,
                hashed_lexical_similarity=_hash_similarity(
                    activation_score,
                    left_coverage,
                    right_coverage,
                    constraint_score,
                    hashed_dense,
                ),
                activation_dense_similarity=activation_dense,
                procedure_dense_coverage_left=procedure_dense_left,
                procedure_dense_coverage_right=procedure_dense_right,
                permission_difference=left.permissions != right.permissions,
                semantic_model_calibrated=(
                    vectorizer_kind != "semantic" or self.thresholds.semantic_calibrated
                ),
            )
        return result


class HybridCandidateRetriever:
    """Compatibility wrapper for the v1 whole-skill retrieval signature."""

    def __init__(self, top_k: int = 5) -> None:
        self.top_k = max(1, int(top_k))

    def retrieve(
        self,
        skills: Iterable[SkillRecord],
        vectors: Mapping[str, Iterable[float] | np.ndarray],
    ) -> dict[tuple[str, str], PairSignals]:
        selected = list(skills)
        dense = _legacy_channel_vectors(selected, vectors)
        result = MultiChannelCandidateRetriever(
            top_k=self.top_k,
            thresholds=ChannelThresholdProfile(semantic_calibrated=True),
        ).retrieve(
            selected,
            {skill.skill_id: extract_skill_sections(skill) for skill in selected},
            dense,
            vectorizer_kind="semantic" if vectors else "lexical_hash",
        )
        by_id = {skill.skill_id: skill for skill in selected}
        # The public legacy facade retains its bounded whole-document lexical
        # recall for callers that have not opted into the segmented API. This
        # is intentionally isolated here; governance analysis uses v2 sections
        # even when no dense vectors are available.
        legacy_scores = {
            _pair(left.skill_id, right.skill_id): _legacy_whole_similarity(left, right)
            for index, left in enumerate(selected)
            for right in selected[index + 1 :]
        }
        for pair in _top_k_pairs(legacy_scores, self.top_k, minimum=0.05):
            if pair not in result:
                left, right = by_id[pair[0]], by_id[pair[1]]
                result[pair] = PairSignals(
                    semantic_similarity=legacy_scores[pair],
                    lexical_similarity=legacy_scores[pair],
                    capability_similarity=capability_similarity(left, right),
                    package_hash_equal=left.content_hash == right.content_hash,
                )
        # Keep the legacy facade's signal shape so old decision callers still
        # use the historical single-score gates. New code calls the multi-
        # channel retriever directly and receives the v2 fields.
        legacy_result: dict[tuple[str, str], PairSignals] = {}
        for pair, signals in result.items():
            fallback = _legacy_whole_similarity(by_id[pair[0]], by_id[pair[1]])
            if fallback == 0.0:
                fallback = signals.hashed_lexical_similarity or signals.activation_lexical_similarity
            legacy_result[pair] = _replace_signal(
                signals,
                signals_version="legacy",
                semantic_similarity=signals.semantic_similarity or fallback,
                lexical_similarity=signals.lexical_similarity or fallback,
                behavior_hash_equal=False,
                execution_present_left=False,
                execution_present_right=False,
                execution_hash_equal=None,
                execution_equivalent=False,
                activation_lexical_similarity=None,
                procedure_coverage_left=None,
                procedure_coverage_right=None,
                constraint_action_similarity=None,
                constraint_polarity_mismatch=False,
                hashed_lexical_similarity=None,
                activation_dense_similarity=None,
                procedure_dense_coverage_left=None,
                procedure_dense_coverage_right=None,
                permission_difference=False,
                semantic_model_calibrated=True,
            )
        result = legacy_result
        # Historical callers used instruction_hash as the exact procedural
        # recall channel and expected a non-null semantic_similarity for the
        # offline lexical path. Keep that behavior only at this wrapper.
        for pair in _equal_hash_pairs(selected, "instruction_hash"):
            left, right = by_id[pair[0]], by_id[pair[1]]
            existing = result.get(pair)
            if existing is None:
                existing = PairSignals(
                    package_hash_equal=left.content_hash == right.content_hash,
                    instruction_hash_equal=True,
                    capability_similarity=capability_similarity(left, right),
                )
            result[pair] = _replace_signal(
                existing,
                instruction_hash_equal=True,
                semantic_model_calibrated=True,
                semantic_similarity=existing.semantic_similarity
                if existing.semantic_similarity is not None
                else 1.0,
                lexical_similarity=existing.lexical_similarity or 0.0,
                hashed_lexical_similarity=existing.hashed_lexical_similarity or 0.0,
            )
        for pair, signals in list(result.items()):
            if not signals.semantic_model_calibrated:
                signals = _replace_signal(signals, semantic_model_calibrated=True)
            if signals.semantic_similarity is None:
                fallback = signals.hashed_lexical_similarity or signals.activation_lexical_similarity
                result[pair] = _replace_signal(
                    signals,
                    semantic_similarity=fallback,
                    lexical_similarity=signals.lexical_similarity or fallback,
                )
            elif signals.lexical_similarity is None and signals.hashed_lexical_similarity is not None:
                result[pair] = _replace_signal(
                    signals, lexical_similarity=signals.hashed_lexical_similarity
                )
        return result


def capability_similarity(left: SkillRecord, right: SkillRecord) -> float:
    """Jaccard similarity with field-qualified capability values."""

    first = _capability_set(left)
    second = _capability_set(right)
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def _capability_set(skill: SkillRecord) -> set[str]:
    fields = {
        "allowed_tools": skill.allowed_tools,
        "tools": skill.tools,
        "permissions": skill.permissions,
        "environments": skill.environments,
        "inputs": skill.inputs,
        "outputs": skill.outputs,
    }
    return {
        f"{field}:{str(value).casefold().strip()}"
        for field, values in fields.items()
        for value in values
        if str(value).strip()
    }


def _equal_hash_pairs(skills: list[SkillRecord], field: str) -> set[tuple[str, str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for skill in skills:
        value = getattr(skill, field, "")
        if value:
            grouped[value].append(skill.skill_id)
    pairs: set[tuple[str, str]] = set()
    for members in grouped.values():
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                pairs.add(_pair(left, right))
    return pairs


def _execution_pairs(skills: list[SkillRecord]) -> set[tuple[str, str]]:
    # The explicit empty-scripts sentinel proves that a package has no
    # executable files, but it is not an executable implementation identity.
    # Unknown/failed reads are represented by None and must never become a
    # broad equality bucket either.
    return {
        pair
        for pair in _equal_hash_pairs(skills, "execution_hash")
        if _skill_by_id(skills, pair[0]).execution_hash != EMPTY_EXECUTION_HASH
        and _skill_by_id(skills, pair[1]).execution_hash != EMPTY_EXECUTION_HASH
        and _skill_by_id(skills, pair[0]).behavior_hash
        != _skill_by_id(skills, pair[1]).behavior_hash
    }


def _execution_equivalent(left: SkillRecord, right: SkillRecord) -> bool:
    if left.execution_hash is None or right.execution_hash is None:
        return False
    return left.execution_hash == right.execution_hash


def _skill_by_id(skills: list[SkillRecord], skill_id: str) -> SkillRecord:
    return next(skill for skill in skills if skill.skill_id == skill_id)


def _procedure_coverage(
    left: list[Counter[str]],
    right: list[Counter[str]],
    idf: dict[str, float],
    threshold: float,
) -> tuple[float | None, float | None]:
    if not left or not right:
        return None, None
    left_scores = [_max_counter_cosine(chunk, right, idf) for chunk in left]
    right_scores = [_max_counter_cosine(chunk, left, idf) for chunk in right]
    return (
        sum(score >= threshold for score in left_scores) / len(left_scores),
        sum(score >= threshold for score in right_scores) / len(right_scores),
    )


def _constraint_similarity(
    left_sections: SkillSections,
    right_sections: SkillSections,
    docs: dict[str, list[Counter[str]]],
    left_id: str,
    right_id: str,
    idf: dict[str, float],
) -> tuple[float | None, bool]:
    left_docs, right_docs = docs[left_id], docs[right_id]
    if not left_docs or not right_docs:
        return None, False
    # Very large Skills can contain dozens of policy sentences. Retain the
    # highest-information clauses for pair scoring; the sparse candidate key
    # has already guaranteed that at least one action term is shared.
    left_rows = _bounded_constraint_rows(left_sections, left_docs, idf)
    right_rows = _bounded_constraint_rows(right_sections, right_docs, idf)
    scores = [
        weighted_counter_cosine(item, candidate, idf)
        for item in left_rows[0]
        for candidate in right_rows[0]
        if not item.keys().isdisjoint(candidate.keys())
    ]
    score = max(scores, default=0.0)
    mismatch = False
    for left_clause in left_rows[1]:
        for right_clause in right_rows[1]:
            if not set(left_clause.action_features).intersection(right_clause.action_features):
                continue
            left_action = lexical_features(" ".join(left_clause.action_features))
            right_action = lexical_features(" ".join(right_clause.action_features))
            if weighted_counter_cosine(left_action, right_action, idf) >= 0.55 and left_clause.polarity != right_clause.polarity:
                mismatch = True
    return score, mismatch


def _bounded_constraint_rows(
    sections: SkillSections,
    docs: list[Counter[str]],
    idf: dict[str, float],
    limit: int = 8,
) -> tuple[list[Counter[str]], list[object]]:
    rows = list(zip(sections.constraint_clauses, docs, strict=False))
    rows.sort(
        key=lambda item: (
            -sum(idf.get(feature, 1.0) for feature in item[1]),
            -len(item[1]),
        )
    )
    selected = rows[:limit]
    return [item[1] for item in selected], [item[0] for item in selected]


def _max_counter_cosine(
    source: Counter[str], candidates: list[Counter[str]], idf: dict[str, float]
) -> float:
    return max(
        (
            weighted_counter_cosine(source, candidate, idf)
            for candidate in candidates
            if not source.keys().isdisjoint(candidate.keys())
        ),
        default=0.0,
    )


def _dense_channel_values(
    skills: list[SkillRecord],
    channel_vectors,
    top_k: int,
    threshold: float,
    vectorizer_kind: Literal["lexical_hash", "semantic"],
) -> dict[tuple[str, str], tuple[float, float, float, float, str]]:
    if channel_vectors is None:
        return {}
    values = getattr(channel_vectors, "values", channel_vectors)
    kind = vectorizer_kind
    dense_activation: dict[str, tuple[np.ndarray, ...]] = {}
    dense_procedure: dict[str, tuple[np.ndarray, ...]] = {}
    for skill in skills:
        channels = values.get(skill.skill_id, {}) if isinstance(values, Mapping) else {}
        dense_activation[skill.skill_id] = tuple(channels.get("activation", ()))
        dense_procedure[skill.skill_id] = tuple(channels.get("procedure", ()))
    result: dict[tuple[str, str], tuple[float, float, float, float, str]] = {}
    for index, left in enumerate(skills):
        left_activation = dense_activation[left.skill_id]
        for right in skills[index + 1 :]:
            right_activation = dense_activation[right.skill_id]
            activation = max(
                (cosine_similarity(a, b) for a in left_activation for b in right_activation),
                default=0.0,
            )
            left_proc = dense_procedure[left.skill_id]
            right_proc = dense_procedure[right.skill_id]
            left_scores = [max((cosine_similarity(a, b) for b in right_proc), default=0.0) for a in left_proc]
            right_scores = [max((cosine_similarity(a, b) for b in left_proc), default=0.0) for a in right_proc]
            left_cov = sum(score >= threshold for score in left_scores) / len(left_scores) if left_scores else 0.0
            right_cov = sum(score >= threshold for score in right_scores) / len(right_scores) if right_scores else 0.0
            score = max(activation, left_cov, right_cov)
            if score >= threshold:
                result[(left.skill_id, right.skill_id)] = (score, activation, left_cov, right_cov, kind)
    per_skill: dict[str, list[tuple[tuple[str, str], float]]] = defaultdict(list)
    for pair, values in result.items():
        per_skill[pair[0]].append((pair, values[0]))
        per_skill[pair[1]].append((pair, values[0]))
    selected: set[tuple[str, str]] = set()
    for rows in per_skill.values():
        rows.sort(key=lambda item: (-item[1], item[0]))
        selected.update(pair for pair, _score in rows[:top_k])
    return {pair: values for pair, values in result.items() if pair in selected}


def _legacy_channel_vectors(skills: list[SkillRecord], vectors: Mapping[str, Iterable[float] | np.ndarray]):
    if not vectors:
        return None
    from skillcheck.embeddings import VectorizerDescriptor
    from skillcheck.vectorization import ChannelVectors

    dimensions = len(np.asarray(next(iter(vectors.values()))).reshape(-1))
    return ChannelVectors(
        descriptor=VectorizerDescriptor(
            backend="legacy",
            model_id="legacy",
            revision="1",
            dimensions=dimensions,
            kind="semantic",
            locality="local",
            normalized=False,
        ),
        values={
            skill.skill_id: {"activation": (np.asarray(vectors[skill.skill_id], dtype=np.float32),)}
            for skill in skills
            if skill.skill_id in vectors
        },
    )


def legacy_channel_vectors(
    skills: Iterable[SkillRecord], vectors: Mapping[str, Iterable[float] | np.ndarray]
):
    """Adapt historical whole-skill rows into a lexical-hash channel view."""

    return _legacy_channel_vectors(list(skills), vectors)


def _hash_similarity(
    activation: float | None,
    left_coverage: float | None,
    right_coverage: float | None,
    constraint: float | None,
    dense_hash: float | None = None,
) -> float | None:
    values = [
        value
        for value in (activation, left_coverage, right_coverage, constraint, dense_hash)
        if value is not None
    ]
    return max(values) if values else None


def _legacy_whole_similarity(left: SkillRecord, right: SkillRecord) -> float:
    first = lexical_features(
        "\n".join(part for part in (activation_text(left), left.body) if part)
    )
    second = lexical_features(
        "\n".join(part for part in (activation_text(right), right.body) if part)
    )
    if not first or not second:
        return 0.0
    dot = sum(value * second.get(key, 0) for key, value in first.items())
    norm = sqrt(sum(value * value for value in first.values()) * sum(value * value for value in second.values()))
    return dot / norm if norm else 0.0


def _top_k_pairs(
    scores: Mapping[tuple[str, str], float], top_k: int, *, minimum: float
) -> set[tuple[str, str]]:
    per_skill: dict[str, list[tuple[tuple[str, str], float]]] = defaultdict(list)
    for pair, score in scores.items():
        if score < minimum:
            continue
        per_skill[pair[0]].append((pair, score))
        per_skill[pair[1]].append((pair, score))
    result: set[tuple[str, str]] = set()
    for rows in per_skill.values():
        rows.sort(key=lambda item: (-item[1], item[0]))
        result.update(pair for pair, _score in rows[:top_k])
    return result


def _shared_feature_pairs(
    documents: Mapping[str, list[Counter[str]]],
) -> set[tuple[str, str]]:
    return set(_shared_feature_scores(documents))


def _shared_feature_scores(
    documents: Mapping[str, list[Counter[str]]],
) -> dict[tuple[str, str], float]:
    members: dict[str, set[str]] = defaultdict(set)
    for skill_id, rows in documents.items():
        for row in rows:
            for feature in row:
                members[feature].add(skill_id)
    pairs: Counter[tuple[str, str]] = Counter()
    for skill_ids in members.values():
        # High-frequency constraint terms are boilerplate, not a useful
        # candidate key. IDF handles their score later; excluding them here
        # keeps the bounded pair union from becoming quadratic again.
        if len(skill_ids) > max(2, len(documents) // 100):
            continue
        ordered = sorted(skill_ids)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                pairs[(left, right)] += 1
    return dict(pairs)


def _replace_signal(signals: PairSignals, **changes) -> PairSignals:
    values = signals.__dict__.copy()
    values.update(changes)
    return PairSignals(**values)


def _permission_conflict(left: list[str], right: list[str]) -> bool:
    first = _permission_modes(left)
    second = _permission_modes(right)
    return any(
        ("read" in first[resource] and "write" in second[resource])
        or ("write" in first[resource] and "read" in second[resource])
        for resource in first.keys() & second.keys()
    )


def _permission_modes(permissions: list[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for permission in permissions:
        normalized = permission.casefold().strip()
        if normalized.endswith("-read"):
            result.setdefault(normalized[:-5], set()).add("read")
        elif normalized.endswith("-write"):
            result.setdefault(normalized[:-6], set()).add("write")
    return result


def _environment_variant(left: list[str], right: list[str]) -> bool:
    first = {value.casefold() for value in left}
    second = {value.casefold() for value in right}
    return bool(first and second and first.isdisjoint(second))


def _pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)
