from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class CandidateScore:
    skill_id: str
    similarity: float


class VectorLike(Protocol):
    skill_id: str
    vector: np.ndarray


def cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
    """Return cosine similarity, treating zero vectors as having no overlap."""

    left = np.asarray(first, dtype=np.float32).reshape(-1)
    right = np.asarray(second, dtype=np.float32).reshape(-1)
    if left.size != right.size:
        return 0.0
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def cosine_top_k(
    query: np.ndarray,
    rows: Iterable[tuple[str, np.ndarray] | VectorLike],
    k: int,
) -> list[CandidateScore]:
    """Return stable descending cosine matches for a query vector."""

    if k <= 0:
        return []
    query_array = np.asarray(query, dtype=np.float32).reshape(-1)
    query_norm = float(np.linalg.norm(query_array))
    if query_norm == 0:
        return []
    matches: list[CandidateScore] = []
    for row in rows:
        if isinstance(row, tuple):
            skill_id, vector = row
        else:
            skill_id = row.skill_id
            vector = row.vector
        vector_array = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector_array.size != query_array.size:
            continue
        vector_norm = float(np.linalg.norm(vector_array))
        if vector_norm == 0:
            similarity = 0.0
        else:
            similarity = float(np.dot(query_array, vector_array) / (query_norm * vector_norm))
        matches.append(CandidateScore(str(skill_id), similarity))
    matches.sort(key=lambda item: (-item.similarity, item.skill_id))
    return matches[:k]


def channel_cosine(rows_left: Iterable[np.ndarray], rows_right: Iterable[np.ndarray]) -> float:
    """Return the best cross-chunk cosine without collapsing channels."""

    left = list(rows_left)
    right = list(rows_right)
    return max(
        (cosine_similarity(first, second) for first in left for second in right),
        default=0.0,
    )


def directional_coverage(
    source: Iterable[np.ndarray], target: Iterable[np.ndarray], threshold: float
) -> float:
    """Fraction of source chunks covered by target chunks at ``threshold``."""

    source_rows = list(source)
    target_rows = list(target)
    if not source_rows or not target_rows:
        return 0.0
    covered = sum(
        channel_cosine((row,), target_rows) >= threshold for row in source_rows
    )
    return covered / len(source_rows)
