from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from skillcheck.catalog.models import (
    LibraryRoot,
    RootScope,
    SkillSnapshot,
    SkillStatus,
    SyncEvent,
    SyncSummary,
)


def test_library_root_validates_scope_and_is_frozen() -> None:
    root = LibraryRoot(
        root_id="root-1",
        path=Path("C:/skills"),
        provider="codex",
        scope="global",
    )

    assert root.scope is RootScope.GLOBAL
    with pytest.raises(ValidationError):
        root.enabled = False


def test_skill_snapshot_uses_independent_list_defaults_and_validates_status() -> None:
    first = SkillSnapshot(
        snapshot_id="snapshot-1",
        skill_id="skill-1",
        root_id="root-1",
        relative_path="example/SKILL.md",
        name="Example",
        content_hash="hash",
        indexed_at=datetime.now(UTC),
    )
    second = SkillSnapshot(
        snapshot_id="snapshot-2",
        skill_id="skill-2",
        root_id="root-1",
        relative_path="second/SKILL.md",
        name="Second",
        content_hash="second-hash",
        indexed_at=datetime.now(UTC),
    )

    assert first.status is SkillStatus.ACTIVE
    assert first.tools == []
    assert first.tools is not second.tools
    with pytest.raises(ValidationError):
        SkillSnapshot(
            snapshot_id="snapshot-3",
            skill_id="skill-1",
            root_id="root-1",
            relative_path="example/SKILL.md",
            name="Example",
            content_hash="hash",
            status="unknown",
            indexed_at=datetime.now(UTC),
        )


def test_sync_models_supply_zero_counts_and_independent_warning_defaults() -> None:
    summary = SyncSummary(revision="revision-1")
    event = SyncEvent(
        event_id="event-1",
        revision="revision-1",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    assert (summary.added, summary.pending, summary.warnings) == (0, 0, [])
    assert (event.updated, event.warnings) == (0, [])
    assert summary.warnings is not event.warnings
