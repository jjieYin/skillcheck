from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from skillcheck.config.models import AppConfig, EmbeddingConfig, SecurityConfig, ThresholdConfig

if TYPE_CHECKING:
    from skillcheck.embeddings import VectorizerDescriptor


SECTION_REVISION = "1"
FEATURE_REVISION = "2"


def embedding_signature(
    config: EmbeddingConfig,
    descriptor: VectorizerDescriptor | None = None,
) -> str:
    """Return the stable identity used for persisted embedding vectors."""

    backend = (descriptor.backend if descriptor is not None else config.backend).strip().casefold()
    model_id = (
        descriptor.model_id
        if descriptor is not None
        else (config.local_model or config.model_id)
    ).strip()
    revision = (
        descriptor.revision if descriptor is not None else config.algorithm_revision
    ).strip()
    dimensions = descriptor.dimensions if descriptor is not None else config.dimensions
    kind = descriptor.kind if descriptor is not None else (
        "lexical_hash" if backend == "hash" else "semantic"
    )
    return (
        f"{backend}:{model_id}:{revision}:d{dimensions}:{kind}:"
        f"section-{SECTION_REVISION}:feature-{FEATURE_REVISION}"
    )


@dataclass(frozen=True)
class GovernancePolicy:
    thresholds: ThresholdConfig
    embedding_signature: str
    security: SecurityConfig
    project_path: Path | None = None
    descriptor: VectorizerDescriptor | None = None
    threshold_profile: str | None = None
    semantic_thresholds_calibrated: bool = False

    @classmethod
    def from_config(
        cls, config: AppConfig, *, project_path: Path | str | None = None
    ) -> GovernancePolicy:
        from skillcheck.embeddings import VectorizerDescriptor

        selected_project = None if project_path is None else Path(project_path).expanduser().resolve()
        backend = config.embedding.backend.strip().casefold()
        descriptor = VectorizerDescriptor(
            backend=backend,
            model_id=(config.embedding.local_model or config.embedding.model_id).strip(),
            revision=config.embedding.algorithm_revision.strip(),
            dimensions=config.embedding.dimensions,
            kind="lexical_hash" if backend == "hash" else "semantic",
            locality="local",
            normalized=True,
        )
        return cls(
            thresholds=config.thresholds,
            embedding_signature=embedding_signature(config.embedding, descriptor),
            security=config.security,
            project_path=selected_project,
            descriptor=descriptor,
            threshold_profile=config.embedding.threshold_profile,
            semantic_thresholds_calibrated=(
                config.embedding.backend.casefold() == "hash"
                or config.embedding.threshold_profile is not None
            ),
        )

    @classmethod
    def default(cls) -> GovernancePolicy:
        return cls.from_config(AppConfig.default(), project_path=Path.cwd())
