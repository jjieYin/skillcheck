from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.models import LibraryRoot, SkillSnapshot, SkillStatus, SyncEvent
from skillcheck.catalog.repository import CatalogRepository, SegmentVectorRecord


@pytest.fixture
def database(tmp_path) -> CatalogDatabase:
    catalog = CatalogDatabase(tmp_path / "catalog.db")
    catalog.initialize()
    return catalog


@pytest.fixture
def repository(database) -> CatalogRepository:
    return CatalogRepository(database)


@pytest.fixture
def root(tmp_path) -> LibraryRoot:
    return LibraryRoot(
        root_id="root-1",
        path=tmp_path / "skills",
        provider="codex",
        scope="project",
        project_path=tmp_path / "project",
    )


@pytest.fixture
def snapshots() -> list[SkillSnapshot]:
    indexed_at = datetime(2026, 8, 10, tzinfo=UTC)
    common = {
        "skill_id": "skill-1",
        "root_id": "root-1",
        "relative_path": "example/SKILL.md",
        "name": "Example",
    }
    return [
        SkillSnapshot(
            snapshot_id="snapshot-1",
            content_hash="hash-1",
            body="old searchable body",
            tools=["工具"],
            indexed_at=indexed_at,
            **common,
        ),
        SkillSnapshot(
            snapshot_id="snapshot-2",
            content_hash="hash-2",
            description="current needle description",
            indexed_at=indexed_at + timedelta(seconds=1),
            **common,
        ),
    ]


def test_upsert_root_is_idempotent_and_round_trips_metadata(repository, root) -> None:
    repository.upsert_root(root)
    repository.upsert_root(root)

    assert repository.list_roots() == [root]


def test_upsert_snapshot_keeps_history_and_moves_current_pointer(
    repository, root, snapshots
) -> None:
    repository.upsert_root(root)
    repository.upsert_snapshot(snapshots[0])
    repository.upsert_snapshot(snapshots[1])
    repository.upsert_snapshot(snapshots[1])

    assert repository.get_current_skill("skill-1") == snapshots[1]
    assert repository.list_snapshots("skill-1") == snapshots


def test_upsert_snapshot_persists_official_instruction_fields(repository, root) -> None:
    repository.upsert_root(root)
    snapshot = SkillSnapshot(
        snapshot_id="snapshot-official",
        skill_id="skill-official",
        root_id="root-1",
        relative_path="official/SKILL.md",
        name="official",
        content_hash="package-hash",
        instruction_hash="instruction-hash",
        license="MIT",
        compatibility="python>=3.11",
        metadata={"owner": "platform"},
        allowed_tools=["http-client"],
        indexed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    repository.upsert_snapshot(snapshot)

    assert repository.get_current_skill("skill-official") == snapshot


def test_mark_missing_changes_current_status_without_deleting_history(
    repository, root, snapshots
) -> None:
    repository.upsert_root(root)
    for snapshot in snapshots:
        repository.upsert_snapshot(snapshot)

    repository.mark_missing("skill-1")

    current = repository.get_current_skill("skill-1")
    assert current is not None
    assert current.status is SkillStatus.MISSING
    assert repository.list_snapshots("skill-1") == snapshots


def test_fts_search_returns_only_the_current_active_snapshot(repository, root, snapshots) -> None:
    repository.upsert_root(root)
    for snapshot in snapshots:
        repository.upsert_snapshot(snapshot)

    assert repository.list_current_skills("needle") == [snapshots[1]]
    assert repository.list_current_skills("old") == []
    repository.mark_missing("skill-1")
    assert repository.list_current_skills("needle") == []


def test_vectors_are_bound_to_snapshot_and_model(repository, root, snapshots) -> None:
    repository.upsert_root(root)
    repository.upsert_snapshot(snapshots[0])
    repository.save_vector("snapshot-1", "local-v1", "hash-1", [0.25, 0.75])
    repository.save_vector("snapshot-1", "local-v2", "hash-1", [1.0])

    rows = repository.get_vectors("local-v1")

    assert len(rows) == 1
    assert (rows[0].snapshot_id, rows[0].model) == ("snapshot-1", "local-v1")
    assert (rows[0].content_hash, rows[0].dimensions) == ("hash-1", 2)
    np.testing.assert_array_equal(rows[0].vector, np.array([0.25, 0.75], dtype=np.float32))


def test_segment_vectors_replace_all_channels_for_one_signature_atomically(
    repository, root, snapshots
) -> None:
    repository.upsert_root(root)
    repository.upsert_snapshot(snapshots[0])
    first_rows = [
        SegmentVectorRecord(
            snapshot_id="snapshot-1",
            model_signature="hash-v2",
            backend_kind="lexical_hash",
            channel="activation",
            chunk_index=0,
            dimensions=2,
            text_hash="text-a",
            vector=np.array([1.0, 0.0], dtype=np.float32),
            created_at="now",
        ),
        SegmentVectorRecord(
            snapshot_id="snapshot-1",
            model_signature="hash-v2",
            backend_kind="lexical_hash",
            channel="procedure",
            chunk_index=0,
            dimensions=2,
            text_hash="text-p0",
            vector=np.array([0.0, 1.0], dtype=np.float32),
            created_at="now",
        ),
    ]
    repository.replace_segment_vectors("snapshot-1", "hash-v2", "lexical_hash", first_rows)

    loaded = repository.get_segment_vectors(["snapshot-1"], "hash-v2")

    assert set(loaded["snapshot-1"]) == {"activation", "procedure"}
    np.testing.assert_array_equal(loaded["snapshot-1"]["procedure"][0], [0.0, 1.0])

    replacement = [
        SegmentVectorRecord(
            snapshot_id="snapshot-1",
            model_signature="hash-v2",
            backend_kind="lexical_hash",
            channel="procedure",
            chunk_index=0,
            dimensions=2,
            text_hash="text-p1",
            vector=np.array([1.0, 1.0], dtype=np.float32),
            created_at="later",
        )
    ]
    repository.replace_segment_vectors("snapshot-1", "hash-v2", "lexical_hash", replacement)

    loaded = repository.get_segment_vectors(["snapshot-1"], "hash-v2")
    assert set(loaded["snapshot-1"]) == {"procedure"}
    np.testing.assert_array_equal(loaded["snapshot-1"]["procedure"][0], [1.0, 1.0])


def test_record_sync_event_is_idempotent_and_preserves_unicode_json(repository, database) -> None:
    event = SyncEvent(
        event_id="event-1",
        revision="revision-1",
        started_at=datetime(2026, 8, 10, tzinfo=UTC),
        completed_at=datetime(2026, 8, 10, 0, 1, tzinfo=UTC),
        added=1,
        warnings=["路径无效"],
    )

    repository.record_sync_event(event)
    repository.record_sync_event(event)

    with sqlite3.connect(database.path) as connection:
        row = connection.execute(
            "SELECT revision, added, warnings_json FROM sync_events WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM sync_events").fetchone()[0]
    assert row == ("revision-1", 1, '["路径无效"]')
    assert count == 1
