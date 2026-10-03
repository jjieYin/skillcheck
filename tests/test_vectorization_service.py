from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot
from skillcheck.catalog.reconcile import CatalogReconciler
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.core.sections import extract_skill_sections
from skillcheck.embeddings import HashVectorizationBackend, VectorizerDescriptor
from skillcheck.vectorization import VectorizationService


def _root(tmp_path: Path) -> LibraryRoot:
    path = tmp_path / "skills"
    path.mkdir()
    return LibraryRoot(root_id="root-1", path=path, provider="codex", scope=RootScope.PROJECT)


def _snapshot() -> SkillSnapshot:
    return SkillSnapshot(
        snapshot_id="snapshot-1",
        skill_id="skill-1",
        root_id="root-1",
        relative_path="example/SKILL.md",
        name="Example",
        description="validate an API request",
        body="First validate the request. Second report errors.",
        content_hash="hash-1",
        indexed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def test_service_preserves_channel_order_and_replaces_signature_rows(tmp_path: Path) -> None:
    root = _root(tmp_path)
    skill_dir = root.path / "example"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: example\ndescription: validate an API request\n---\n"
        "## Procedure\n\nFirst validate the request.\n\nSecond report errors.\n",
        encoding="utf-8",
    )
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    backend = HashVectorizationBackend(dimensions=8)
    backend.model_signature = "hash:hash-v1:2:d8:lexical_hash:section-1:feature-2"
    reconciler = CatalogReconciler(repository, embedding=backend)

    reconciler.reconcile([root])

    snapshot = repository.list_current_skills()[0]
    records = repository.get_segment_vector_records(
        [snapshot.snapshot_id], backend.model_signature
    )
    assert records[0].channel == "activation"
    assert [record.channel for record in records[1:]] == ["procedure"] * (len(records) - 1)
    assert [record.chunk_index for record in records] == list(range(len(records)))[:1] + list(
        range(len(records) - 1)
    )
    assert all(record.text_hash.startswith("sha256:") for record in records)
    assert all(record.backend_kind == "lexical_hash" for record in records)

    sections = extract_skill_sections(CatalogReconciler._record(snapshot))
    assert sections.activation_text
    assert sections.procedure_chunks


def test_service_rejects_bad_batch_before_replacing_previous_rows(tmp_path: Path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    root = _root(tmp_path)
    repository.upsert_root(root)
    snapshot = _snapshot()
    repository.upsert_snapshot(snapshot)
    backend = HashVectorizationBackend(dimensions=4)
    backend.model_signature = "hash:good"
    service = VectorizationService(repository, backend)
    record = CatalogReconciler._record(snapshot)
    sections = extract_skill_sections(record)
    encoded = service.encode_record(record, sections)
    service.replace_snapshot(snapshot.snapshot_id, sections, encoded)
    before = repository.get_segment_vector_records([snapshot.snapshot_id], "hash:good")

    class BadBackend:
        descriptor = VectorizerDescriptor(
            backend="fake",
            model_id="bad",
            revision="1",
            dimensions=4,
            kind="semantic",
            locality="local",
            normalized=False,
        )

        def encode(self, inputs):
            return np.zeros((max(0, len(inputs) - 1), 4), dtype=np.float32)

    with pytest.raises(ValueError, match="row count"):
        VectorizationService(repository, BadBackend()).encode_record(record, sections)

    after = repository.get_segment_vector_records([snapshot.snapshot_id], "hash:good")
    assert [(row.channel, row.chunk_index, row.text_hash) for row in after] == [
        (row.channel, row.chunk_index, row.text_hash) for row in before
    ]


def test_segment_signature_isolation_does_not_read_old_vectors(tmp_path: Path) -> None:
    database = CatalogDatabase(tmp_path / "catalog.db")
    database.initialize()
    repository = CatalogRepository(database)
    root = _root(tmp_path)
    repository.upsert_root(root)
    snapshot = _snapshot()
    repository.upsert_snapshot(snapshot)
    backend = HashVectorizationBackend(dimensions=4)
    service = VectorizationService(repository, backend, model_signature="hash:one")
    record = CatalogReconciler._record(snapshot)
    sections = extract_skill_sections(record)
    service.replace_snapshot(
        snapshot.snapshot_id,
        sections,
        service.encode_record(record, sections),
    )

    assert service.load([snapshot.snapshot_id])
    assert repository.get_segment_vectors([snapshot.snapshot_id], "hash:two") == {}
