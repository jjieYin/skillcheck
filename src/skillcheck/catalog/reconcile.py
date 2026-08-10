"""Incrementally reconcile local Skill files into the catalog."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from skillcheck.catalog.ids import skill_id, snapshot_id
from skillcheck.catalog.models import (
    LibraryRoot,
    SkillSnapshot,
    SkillStatus,
    SyncEvent,
    SyncSummary,
)
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.core.parser import SkillParseError, parse_skill
from skillcheck.models.common import Provider, Scope


class CatalogReconciler:
    """Apply a bounded filesystem observation to the immutable catalog."""

    def __init__(self, repository: CatalogRepository, *, embedding=None) -> None:
        self.repository = repository
        self.embedding = embedding
        self._fingerprints: dict[Path, tuple[int, int]] = {}

    def reconcile(
        self, roots: list[LibraryRoot], changed_paths: list[Path] | None = None
    ) -> SyncSummary:
        started_at = datetime.now(UTC)
        enabled_roots = sorted((root for root in roots if root.enabled), key=lambda root: root.root_id)
        observations: dict[str, dict[str, SkillSnapshot]] = {}
        warnings: list[str] = []
        invalid = 0
        for root in enabled_roots:
            root_observations, root_warnings = self._observe(root, changed_paths)
            observations[root.root_id] = root_observations
            warnings.extend(root_warnings)
            invalid += sum(item.status is SkillStatus.INVALID for item in root_observations.values())

        completed_at = datetime.now(UTC)
        revision = f"sync-{completed_at.strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:8]}"
        with self.repository.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for root in enabled_roots:
                    self._upsert_root(connection, root)
                added, updated, removed = self._apply(connection, enabled_roots, observations, changed_paths)
                event = SyncEvent(
                    event_id=f"event-{uuid4().hex}",
                    revision=revision,
                    started_at=started_at,
                    completed_at=completed_at,
                    added=added,
                    updated=updated,
                    removed=removed,
                    invalid=invalid,
                    warnings=warnings,
                )
                connection.execute(
                    """
                    INSERT INTO sync_events (event_id, revision, started_at, completed_at, added, updated,
                                             removed, invalid, warnings_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.revision,
                        event.started_at.isoformat(),
                        event.completed_at.isoformat(),
                        event.added,
                        event.updated,
                        event.removed,
                        event.invalid,
                        json.dumps(event.warnings, ensure_ascii=False),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return SyncSummary(
            revision=revision,
            added=added,
            updated=updated,
            removed=removed,
            invalid=invalid,
            warnings=warnings,
        )

    def _observe(
        self, root: LibraryRoot, changed_paths: list[Path] | None
    ) -> tuple[dict[str, SkillSnapshot], list[str]]:
        snapshots: dict[str, SkillSnapshot] = {}
        warnings: list[str] = []
        for path in self._skill_files(root, changed_paths):
            try:
                stat = path.stat()
                fingerprint = (stat.st_size, stat.st_mtime_ns)
                # The cheap stat comparison always precedes parsing/content hashing.  The
                # fingerprint is retained for watcher callers; the database remains the source
                # of truth across process restarts.
                self._fingerprints[path] = fingerprint
                relative_path = path.relative_to(root.path).as_posix()
                identity = skill_id(root.provider, root.scope.value, relative_path)
                try:
                    parsed = parse_skill(
                        path.parent, provider=Provider(root.provider), scope=Scope(root.scope.value)
                    )
                    snapshots[relative_path] = SkillSnapshot(
                        snapshot_id=snapshot_id(identity, parsed.content_hash),
                        skill_id=identity,
                        root_id=root.root_id,
                        relative_path=relative_path,
                        name=parsed.name,
                        description=parsed.description,
                        body=parsed.body,
                        content_hash=parsed.content_hash,
                        tools=parsed.tools,
                        permissions=parsed.permissions,
                        environments=parsed.environments,
                        inputs=parsed.inputs,
                        outputs=parsed.outputs,
                        indexed_at=datetime.now(UTC),
                    )
                except SkillParseError as error:
                    content_hash = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
                    snapshots[relative_path] = SkillSnapshot(
                        snapshot_id=snapshot_id(identity, content_hash),
                        skill_id=identity,
                        root_id=root.root_id,
                        relative_path=relative_path,
                        name=path.parent.name,
                        content_hash=content_hash,
                        status=SkillStatus.INVALID,
                        indexed_at=datetime.now(UTC),
                        parse_error=str(error),
                    )
            except OSError as error:
                warnings.append(f"cannot inspect {path}: {error}")
        return snapshots, warnings

    @staticmethod
    def _skill_files(root: LibraryRoot, changed_paths: list[Path] | None) -> list[Path]:
        if changed_paths is None:
            try:
                return sorted(root.path.rglob("SKILL.md"), key=lambda path: path.as_posix())
            except OSError:
                return []
        selected: set[Path] = set()
        for changed in changed_paths:
            path = Path(changed)
            try:
                path.resolve().relative_to(root.path.resolve())
            except (OSError, ValueError):
                continue
            candidate = path if path.name == "SKILL.md" else CatalogReconciler._skill_file_for(path, root.path)
            if candidate.is_file():
                selected.add(candidate)
        return sorted(selected, key=lambda path: path.as_posix())

    @staticmethod
    def _skill_file_for(path: Path, root_path: Path) -> Path:
        """Return the enclosing Skill file when an asset inside a Skill changed."""
        candidate = path if path.is_dir() else path.parent
        while True:
            skill_file = candidate / "SKILL.md"
            if skill_file.is_file():
                return skill_file
            if candidate == root_path or candidate.parent == candidate:
                return path / "SKILL.md"
            candidate = candidate.parent

    def _apply(
        self,
        connection: sqlite3.Connection,
        roots: list[LibraryRoot],
        observations: dict[str, dict[str, SkillSnapshot]],
        changed_paths: list[Path] | None,
    ) -> tuple[int, int, int]:
        added = updated = removed = 0
        for root in roots:
            current = connection.execute(
                """SELECT skills.skill_id, skills.relative_path, skills.status,
                          skill_snapshots.content_hash, skill_snapshots.status AS snapshot_status
                   FROM skills JOIN skill_snapshots ON skills.current_snapshot_id = skill_snapshots.snapshot_id
                   WHERE skills.root_id = ?""",
                (root.root_id,),
            ).fetchall()
            previous = {row["relative_path"]: row for row in current}
            observed = observations[root.root_id]
            for relative_path, item in observed.items():
                before = previous.get(relative_path)
                if before is not None and before["content_hash"] == item.content_hash and before[
                    "snapshot_status"
                ] == item.status.value:
                    continue
                if before is None:
                    added += 1
                else:
                    updated += 1
                self._upsert_snapshot(connection, item)
                if before is None and item.status is SkillStatus.ACTIVE and self.embedding is not None:
                    vector = self.embedding.encode([self._embedding_text(item)])[0]
                    self._save_vector(connection, item, vector)
            candidates = previous if changed_paths is None else {
                path: row for path, row in previous.items() if self._is_changed(root, path, changed_paths)
            }
            for relative_path, row in candidates.items():
                if relative_path not in observed and not (root.path / relative_path).is_file():
                    connection.execute(
                        "UPDATE skills SET status = ?, updated_at = ? WHERE skill_id = ?",
                        (SkillStatus.MISSING.value, datetime.now(UTC).isoformat(), row["skill_id"]),
                    )
                    connection.execute(
                        "DELETE FROM skill_fts WHERE snapshot_id = (SELECT current_snapshot_id FROM skills WHERE skill_id = ?)",
                        (row["skill_id"],),
                    )
                    removed += 1
        return added, updated, removed

    @staticmethod
    def _is_changed(root: LibraryRoot, relative_path: str, changed_paths: list[Path]) -> bool:
        skill_path = root.path / relative_path
        for changed in changed_paths:
            changed_path = Path(changed)
            if changed_path == skill_path or changed_path == skill_path.parent:
                return True
        return False

    @staticmethod
    def _upsert_root(connection: sqlite3.Connection, root: LibraryRoot) -> None:
        now = datetime.now(UTC).isoformat()
        connection.execute(
            """INSERT INTO library_roots (root_id, path, provider, scope, project_path, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(root_id) DO UPDATE SET path=excluded.path, provider=excluded.provider,
                   scope=excluded.scope, project_path=excluded.project_path, enabled=excluded.enabled,
                   updated_at=excluded.updated_at""",
            (root.root_id, str(root.path), root.provider, root.scope.value,
             str(root.project_path) if root.project_path else None, int(root.enabled), now, now),
        )

    @staticmethod
    def _upsert_snapshot(connection: sqlite3.Connection, item: SkillSnapshot) -> None:
        now = datetime.now(UTC).isoformat()
        connection.execute(
            """INSERT INTO skills (skill_id, root_id, relative_path, status, current_snapshot_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skill_id) DO UPDATE SET root_id=excluded.root_id, relative_path=excluded.relative_path,
                   status=excluded.status, current_snapshot_id=excluded.current_snapshot_id, updated_at=excluded.updated_at""",
            (item.skill_id, item.root_id, item.relative_path, item.status.value, item.snapshot_id, now, now),
        )
        connection.execute(
            """INSERT OR IGNORE INTO skill_snapshots (snapshot_id, skill_id, root_id, relative_path, name,
               description, body, content_hash, status, tools_json, permissions_json, environments_json,
               inputs_json, outputs_json, indexed_at, parse_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.snapshot_id, item.skill_id, item.root_id, item.relative_path, item.name, item.description,
             item.body, item.content_hash, item.status.value, json.dumps(item.tools, ensure_ascii=False),
             json.dumps(item.permissions, ensure_ascii=False), json.dumps(item.environments, ensure_ascii=False),
             json.dumps(item.inputs, ensure_ascii=False), json.dumps(item.outputs, ensure_ascii=False),
             item.indexed_at.isoformat(), item.parse_error),
        )
        connection.execute(
            "DELETE FROM skill_fts WHERE snapshot_id IN (SELECT snapshot_id FROM skill_snapshots WHERE skill_id = ?)",
            (item.skill_id,),
        )
        if item.status is SkillStatus.ACTIVE:
            connection.execute("INSERT INTO skill_fts(snapshot_id, name, description, body) VALUES (?, ?, ?, ?)",
                               (item.snapshot_id, item.name, item.description, item.body))

    @staticmethod
    def _embedding_text(item: SkillSnapshot) -> str:
        return "\n".join(part for part in (item.name, item.description, item.body) if part)

    def _save_vector(self, connection: sqlite3.Connection, item: SkillSnapshot, vector) -> None:
        array = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(-1))
        connection.execute(
            """INSERT INTO vectors (snapshot_id, model, dimensions, content_hash, vector, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item.snapshot_id, self.embedding.model_id, int(array.size), item.content_hash, array.tobytes(),
             datetime.now(UTC).isoformat()),
        )
