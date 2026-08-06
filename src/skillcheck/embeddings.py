from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from skillcheck.models import SkillRecord


class EmbeddingUnavailable(RuntimeError):
    """Raised when an optional embedding backend cannot be loaded."""


class EmbeddingBackend(Protocol):
    model_id: str

    def encode(self, texts: list[str]) -> np.ndarray:
        ...


class HashEmbeddingBackend:
    """Offline deterministic feature-hash embedding for the base installation."""

    def __init__(self, dimensions: int = 256, model_id: str | None = None) -> None:
        if dimensions < 2:
            raise ValueError("embedding dimensions must be at least 2")
        self.dimensions = dimensions
        self.model_id = model_id or f"hash-v1-{dimensions}"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            tokens = _tokens(text)
            if not tokens:
                tokens = [text]
            for token in tokens:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vectors[row, index] += sign
            vectors[row] = _normalize(vectors[row])
        return vectors


class SentenceTransformerBackend:
    """Optional local sentence-transformers adapter, loaded only on demand."""

    def __init__(self, model_name: str, *, device: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingUnavailable(
                "sentence-transformers is not installed; install skillcheck[local-embedding]"
            ) from exc
        self.model_id = model_name
        try:
            self._model = SentenceTransformer(model_name, device=device)
        except Exception as exc:
            raise EmbeddingUnavailable(f"cannot load embedding model: {model_name}") from exc

    def encode(self, texts: list[str]) -> np.ndarray:
        values = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(values, dtype=np.float32)


def skill_embedding_text(skill: SkillRecord) -> str:
    fields = [
        f"name: {skill.name}",
        f"description: {skill.description}",
        f"tools: {', '.join(skill.tools)}",
        f"permissions: {', '.join(skill.permissions)}",
        f"environments: {', '.join(skill.environments)}",
        f"inputs: {', '.join(skill.inputs)}",
        f"outputs: {', '.join(skill.outputs)}",
        "body:",
        skill.body,
    ]
    return "\n".join(fields)


def backend_from_config(config) -> EmbeddingBackend:
    if config.backend == "hash":
        return HashEmbeddingBackend(config.dimensions, config.model_id)
    if config.backend in {"sentence-transformers", "local"}:
        model_name = config.local_model or config.model_id
        return SentenceTransformerBackend(model_name)
    raise EmbeddingUnavailable(f"unsupported embedding backend: {config.backend}")


def _tokens(text: str) -> list[str]:
    normalized = "".join(character.lower() if character.isalnum() else " " for character in text)
    return [token for token in normalized.split() if token]


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm
