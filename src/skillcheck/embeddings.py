"""Pluggable, channel-aware vectorization backends.

The default backend remains deterministic lexical hashing. Optional semantic
models are loaded only through the explicit local registry entry.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

import numpy as np

from skillcheck.core.features import activation_text, lexical_features, procedure_text
from skillcheck.core.sections import EmbeddingChannel
from skillcheck.models import SkillRecord


class EmbeddingUnavailable(RuntimeError):
    """Raised when an optional embedding backend cannot be loaded."""


@dataclass(frozen=True)
class VectorizerDescriptor:
    backend: str
    model_id: str
    revision: str
    dimensions: int
    kind: Literal["lexical_hash", "semantic"]
    locality: Literal["local", "remote"]
    normalized: bool


@dataclass(frozen=True)
class VectorizationInput:
    key: str
    channel: EmbeddingChannel
    text: str


class VectorizationBackend(Protocol):
    descriptor: VectorizerDescriptor

    def encode(self, inputs: Sequence[VectorizationInput]) -> np.ndarray:
        ...


EmbeddingBackend: TypeAlias = VectorizationBackend
InputLike: TypeAlias = VectorizationInput | str


def validate_vector_batch(
    inputs: Sequence[VectorizationInput],
    values: np.ndarray,
    descriptor: VectorizerDescriptor,
) -> np.ndarray:
    """Validate one complete model batch before it can reach persistence."""

    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError("vector batch must be a two-dimensional matrix")
    if array.shape[0] != len(inputs):
        raise ValueError("vector batch row count does not match inputs")
    if descriptor.dimensions <= 0 or array.shape[1] != descriptor.dimensions:
        raise ValueError("vector batch dimensions do not match the descriptor")
    if not np.isfinite(array).all():
        raise ValueError("vector batch contains non-finite values")
    if descriptor.normalized and array.shape[0]:
        norms = np.linalg.norm(array, axis=1)
        if np.any(norms <= 0) or np.any(np.abs(norms - 1.0) > 1e-3):
            raise ValueError("normalized vector batch contains non-unit rows")
    return np.ascontiguousarray(array)


class HashVectorizationBackend:
    """Offline deterministic feature-hash backend classified as lexical."""

    def __init__(
        self,
        dimensions: int = 256,
        model_id: str | None = None,
        *,
        revision: str = "2",
    ) -> None:
        if dimensions < 2:
            raise ValueError("embedding dimensions must be at least 2")
        self.descriptor = VectorizerDescriptor(
            backend="hash",
            model_id=model_id or f"hash-v1-{dimensions}",
            revision=revision,
            dimensions=dimensions,
            kind="lexical_hash",
            locality="local",
            normalized=True,
        )
        self.model_id = self.descriptor.model_id
        self.model_signature = self.descriptor.model_id

    def encode(self, inputs: Sequence[InputLike]) -> np.ndarray:
        normalized_inputs = _coerce_inputs(inputs)
        vectors = np.zeros(
            (len(normalized_inputs), self.descriptor.dimensions), dtype=np.float32
        )
        for row, item in enumerate(normalized_inputs):
            features = lexical_features(item.text)
            if not features and item.text:
                features = {item.text.casefold(): 1}
            for feature, count in features.items():
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.descriptor.dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vectors[row, index] += sign * float(count)
            vectors[row] = _normalize(vectors[row])
        return vectors

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self.encode(list(texts))


class SentenceTransformerVectorizationBackend:
    """Optional local sentence-transformers adapter, loaded only on demand."""

    def __init__(
        self,
        model_name: str,
        *,
        dimensions: int = 384,
        revision: str = "1",
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EmbeddingUnavailable(
                "sentence-transformers is not installed; install skillcheck[local-embedding]"
            ) from exc
        self.descriptor = VectorizerDescriptor(
            backend="sentence-transformers",
            model_id=model_name,
            revision=revision,
            dimensions=dimensions,
            kind="semantic",
            locality="local",
            normalized=True,
        )
        self.model_id = model_name
        self.model_signature = model_name
        self.batch_size = batch_size
        try:
            self._model = SentenceTransformer(model_name, device=device)
        except Exception as exc:
            raise EmbeddingUnavailable(f"cannot load embedding model: {model_name}") from exc

    def encode(self, inputs: Sequence[InputLike]) -> np.ndarray:
        normalized_inputs = _coerce_inputs(inputs)
        try:
            values = self._model.encode(
                [item.text for item in normalized_inputs],
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=self.batch_size,
            )
        except Exception as exc:
            raise EmbeddingUnavailable("embedding model encoding failed") from exc
        return validate_vector_batch(normalized_inputs, values, self.descriptor)

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        return self.encode(list(texts))


# Compatibility names used by the v0.5 public surface.
HashEmbeddingBackend = HashVectorizationBackend
SentenceTransformerBackend = SentenceTransformerVectorizationBackend


class FakeVectorizationBackend:
    """Deterministic test-only backend; never registered for production config."""

    def __init__(self, mapping: dict[str, Sequence[float]]) -> None:
        self.mapping = {key: np.asarray(value, dtype=np.float32) for key, value in mapping.items()}
        dimensions = len(next(iter(self.mapping.values()))) if self.mapping else 0
        self.descriptor = VectorizerDescriptor(
            backend="fake",
            model_id="fake-v1",
            revision="1",
            dimensions=dimensions,
            kind="semantic",
            locality="local",
            normalized=False,
        )
        self.calls: list[list[VectorizationInput]] = []

    def encode(self, inputs: Sequence[VectorizationInput]) -> np.ndarray:
        batch = list(inputs)
        self.calls.append(batch)
        return np.asarray([self.mapping[item.text] for item in batch], dtype=np.float32)


BackendFactory: TypeAlias = Callable[[object], VectorizationBackend]


class VectorizationRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, BackendFactory] = {}

    def register(self, name: str, factory: BackendFactory) -> None:
        self._factories[name.casefold()] = factory

    def create(self, name: str, config: object) -> VectorizationBackend:
        try:
            factory = self._factories[name.casefold()]
        except KeyError as exc:
            raise EmbeddingUnavailable(f"unsupported embedding backend: {name}") from exc
        return factory(config)


DEFAULT_VECTORIZATION_REGISTRY = VectorizationRegistry()
DEFAULT_VECTORIZATION_REGISTRY.register(
    "hash",
    lambda config: HashVectorizationBackend(
        config.dimensions, config.model_id, revision=config.algorithm_revision
    ),
)
DEFAULT_VECTORIZATION_REGISTRY.register(
    "sentence-transformers",
    lambda config: SentenceTransformerVectorizationBackend(
        config.local_model or config.model_id,
        dimensions=config.dimensions,
        revision=config.algorithm_revision,
        device=config.device,
        batch_size=config.batch_size,
    ),
)
DEFAULT_VECTORIZATION_REGISTRY.register(
    "local",
    DEFAULT_VECTORIZATION_REGISTRY._factories["sentence-transformers"],
)


def skill_embedding_text(skill: SkillRecord) -> str:
    return "\n".join(part for part in (activation_text(skill), procedure_text(skill)) if part)


def backend_from_config(config) -> VectorizationBackend:
    """Instantiate only a registered backend; model failures stay explicit."""

    from skillcheck.governance.policy import embedding_signature

    backend = DEFAULT_VECTORIZATION_REGISTRY.create(config.backend, config)
    signature = embedding_signature(config)
    backend.model_id = signature
    backend.model_signature = signature
    return backend


def backend_for_config(config) -> VectorizationBackend:
    """Use the requested backend or an explicitly marked local hash fallback."""

    try:
        return backend_from_config(config)
    except EmbeddingUnavailable as error:
        fallback = HashVectorizationBackend(
            config.dimensions,
            f"hash-v1-{config.dimensions}",
            revision=getattr(config, "algorithm_revision", "2"),
        )
        fallback.degraded_reason = "optional vectorizer unavailable; using offline lexical hash"
        fallback.degraded_error = str(error)
        return fallback


def _coerce_inputs(inputs: Sequence[InputLike]) -> list[VectorizationInput]:
    result: list[VectorizationInput] = []
    for index, item in enumerate(inputs):
        if isinstance(item, VectorizationInput):
            result.append(item)
        else:
            result.append(VectorizationInput(key=str(index), channel="procedure", text=str(item)))
    return result


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0 else vector / norm
