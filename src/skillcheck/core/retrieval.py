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
