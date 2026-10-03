"""Segment-aware vectorization and persistence orchestration.

The service is deliberately small: extraction is owned by ``core.sections``,
backend loading by ``embeddings``, and durable writes by the catalog repository.
Keeping those boundaries separate makes a failed model batch unable to leave a
partially replaced snapshot behind.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from skillcheck.catalog.repository import CatalogRepository, SegmentVectorRecord
from skillcheck.core.sections import EmbeddingChannel, SkillSections
from skillcheck.embeddings import (
    VectorizationBackend,
    VectorizationInput,
    VectorizerDescriptor,
    validate_vector_batch,
)
from skillcheck.models.skill import SkillRecord


@dataclass(frozen=True)
class ChannelVectors:
    """Encoded vectors grouped by skill key and logical channel.

    ``text_hashes`` is kept alongside the vectors so persistence can prove that
    a stored row belongs to the exact text that was encoded.  It has a default
    for callers that only need in-memory retrieval fixtures.
    """

    descriptor: VectorizerDescriptor
    values: Mapping[str, Mapping[EmbeddingChannel, tuple[np.ndarray, ...]]]
    text_hashes: Mapping[str, Mapping[EmbeddingChannel, tuple[str, ...]]] = field(
        default_factory=dict
    )


class VectorizationService:
    """Encode sections and replace one snapshot's current model signature."""

    def __init__(
        self,
        repository: CatalogRepository | None,
        backend: VectorizationBackend,
        *,
        model_signature: str | None = None,
    ) -> None:
        self.repository = repository
        self.backend = backend
        self.descriptor = backend.descriptor
        self.model_signature = (
            model_signature
            or getattr(backend, "model_signature", None)
            or getattr(backend, "model_id", None)
            or self.descriptor.model_id
        )

    @staticmethod
    def build_inputs(
        record: SkillRecord, sections: SkillSections
    ) -> tuple[VectorizationInput, ...]:
        """Build deterministic activation/procedure/constraint input order."""

        result: list[VectorizationInput] = []
        if sections.activation_text.strip():
            result.append(
                VectorizationInput(
                    key=f"{record.skill_id}:activation:0",
                    channel="activation",
                    text=sections.activation_text.strip(),
                )
            )
        for index, chunk in enumerate(sections.procedure_chunks):
            if chunk.strip():
                result.append(
                    VectorizationInput(
                        key=f"{record.skill_id}:procedure:{index}",
                        channel="procedure",
                        text=chunk.strip(),
                    )
                )
        for index, clause in enumerate(sections.constraint_clauses):
            if clause.text.strip():
                result.append(
                    VectorizationInput(
                        key=f"{record.skill_id}:constraint:{index}",
                        channel="constraint",
                        text=clause.text.strip(),
                    )
                )
        return tuple(result)

    @classmethod
    def expected_text_hashes(
        cls, record: SkillRecord, sections: SkillSections
    ) -> dict[EmbeddingChannel, tuple[str, ...]]:
        """Return the exact text binding expected for a parsed Skill."""

        grouped: dict[EmbeddingChannel, list[str]] = {}
        del record  # Section extraction has already normalized the source text.
        if sections.activation_text.strip():
            grouped["activation"] = [_text_hash(sections.activation_text.strip())]
        for chunk in sections.procedure_chunks:
            if chunk.strip():
                grouped.setdefault("procedure", []).append(_text_hash(chunk.strip()))
        for clause in sections.constraint_clauses:
            if clause.text.strip():
                grouped.setdefault("constraint", []).append(_text_hash(clause.text.strip()))
        return {channel: tuple(values) for channel, values in grouped.items()}

    def encode_record(
        self, record: SkillRecord, sections: SkillSections
    ) -> ChannelVectors:
        inputs = self.build_inputs(record, sections)
        if not inputs:
            return ChannelVectors(
                descriptor=self.descriptor,
                values={record.skill_id: {}},
                text_hashes={record.skill_id: {}},
            )
        values = validate_vector_batch(
            inputs,
            self.backend.encode(inputs),
            self.descriptor,
        )
        grouped: dict[str, dict[EmbeddingChannel, list[np.ndarray]]] = {
            record.skill_id: {}
        }
        hashes: dict[str, dict[EmbeddingChannel, list[str]]] = {record.skill_id: {}}
        for row, item in zip(values, inputs, strict=True):
            grouped[record.skill_id].setdefault(item.channel, []).append(row.copy())
            hashes[record.skill_id].setdefault(item.channel, []).append(_text_hash(item.text))
        return ChannelVectors(
            descriptor=self.descriptor,
            values={
                skill_id: {
                    channel: tuple(rows)
                    for channel, rows in channels.items()
                }
                for skill_id, channels in grouped.items()
            },
            text_hashes={
                skill_id: {
                    channel: tuple(rows)
                    for channel, rows in channels.items()
                }
                for skill_id, channels in hashes.items()
            },
        )

    def replace_snapshot(
        self,
        snapshot_id: str,
        sections: SkillSections,
        encoded: ChannelVectors,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """Replace every current-signature segment for one snapshot atomically."""

        if self.repository is None:
            raise ValueError("a repository is required to persist segment vectors")
        if encoded.descriptor != self.descriptor:
            raise ValueError("encoded vector descriptor does not match the service")
        values = encoded.values.get(snapshot_id, {})
        # A source record is normally keyed by skill_id while the durable row
        # uses snapshot_id; accept the single-record form without guessing when
        # callers use those two identifiers differently.
        if not values and len(encoded.values) == 1:
            values = next(iter(encoded.values.values()))
        hashes = encoded.text_hashes.get(snapshot_id, {})
        if not hashes and len(encoded.text_hashes) == 1:
            hashes = next(iter(encoded.text_hashes.values()))
        expected_hashes = self.expected_text_hashes(
            SkillRecord(
                skill_id=snapshot_id,
                name="",
                root_path=".",
                body="",
                content_hash="",
            ),
            sections,
        )
        # ``sections`` does not contain metadata, so the expected hash check
        # is channel/text based and does not depend on a Skill identifier.
        if {
            channel: tuple(channel_hashes)
            for channel, channel_hashes in hashes.items()
            if channel_hashes
        } != expected_hashes:
            raise ValueError("encoded segment text hashes do not match sections")
        rows: list[SegmentVectorRecord] = []
        for channel in ("activation", "procedure", "constraint"):
            channel_values = tuple(values.get(channel, ()))
            channel_hashes = tuple(hashes.get(channel, ()))
            if len(channel_values) != len(channel_hashes):
                raise ValueError(f"missing text hashes for {channel} vectors")
            for index, (vector, text_hash) in enumerate(zip(channel_values, channel_hashes, strict=True)):
                array = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(-1))
                if array.size != self.descriptor.dimensions or not np.isfinite(array).all():
                    raise ValueError("encoded segment vector does not match descriptor")
                rows.append(
                    SegmentVectorRecord(
                        snapshot_id=snapshot_id,
                        model_signature=self.model_signature,
                        backend_kind=self.descriptor.kind,
                        channel=channel,
                        chunk_index=index,
                        dimensions=int(array.size),
                        text_hash=text_hash,
                        vector=array,
                        created_at=_now(),
                    )
                )
        self.repository.replace_segment_vectors(
            snapshot_id,
            self.model_signature,
            self.descriptor.kind,
            rows,
            connection=connection,
        )

    def load(
        self,
        snapshot_ids: list[str] | tuple[str, ...],
        *,
        expected_text_hashes: Mapping[str, Mapping[EmbeddingChannel, tuple[str, ...]]] | None = None,
    ) -> dict[str, dict[str, tuple[np.ndarray, ...]]]:
        if self.repository is None:
            return {}
        records = self.repository.get_segment_vector_records(snapshot_ids, self.model_signature)
        grouped_records: dict[str, dict[str, list[SegmentVectorRecord]]] = {}
        for record in records:
            if (
                record.backend_kind != self.descriptor.kind
                or record.dimensions != self.descriptor.dimensions
            ):
                continue
            grouped_records.setdefault(record.snapshot_id, {}).setdefault(
                record.channel, []
            ).append(record)
        result: dict[str, dict[str, tuple[np.ndarray, ...]]] = {}
        for snapshot_id, channels in grouped_records.items():
            actual_hashes = {
                channel: tuple(item.text_hash for item in sorted(rows, key=lambda row: row.chunk_index))
                for channel, rows in channels.items()
            }
            expected = expected_text_hashes.get(snapshot_id) if expected_text_hashes else None
            if expected is not None and actual_hashes != dict(expected):
                continue
            result[snapshot_id] = {
                channel: tuple(item.vector.copy() for item in sorted(rows, key=lambda row: row.chunk_index))
                for channel, rows in channels.items()
            }
        return result


def _text_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
