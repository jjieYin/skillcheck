"""Compatibility exports for the v2 retrieval core."""

from skillcheck.core.retrieval import CandidateScore, VectorLike, cosine_top_k

__all__ = ["CandidateScore", "VectorLike", "cosine_top_k"]
