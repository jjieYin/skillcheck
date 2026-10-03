"""Incrementally reconcile local Skill files into the catalog."""

from __future__ import annotations

import hashlib
import json
import os
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
from skillcheck.core.features import activation_text, procedure_text
from skillcheck.core.parser import SkillParseError, parse_skill
from skillcheck.core.sections import extract_skill_sections
from skillcheck.embeddings import EmbeddingUnavailable
from skillcheck.models.common import Provider, Scope
from skillcheck.models.skill import SkillRecord
from skillcheck.vectorization import VectorizationService


class CatalogReconciler:
    """Apply a bounded filesystem observation to the immutable catalog."""

    def __init__(self, repository: CatalogRepository, *, embedding=None) -> None:
        self.repository = repository
        self.embedding = embedding
        self.vectorization = (
            VectorizationService(repository, embedding)
            if embedding is not None and hasattr(embedding, "descriptor")
            else None
        )
        self._fingerprints: dict[Path, tuple[tuple[tuple[str, int, int], ...], str]] = {}
        self._vectorization_warnings: list[str] = []

    def reconcile(
        self, roots: list[LibraryRoot], changed_paths: list[Path] | None = None
    ) -> SyncSummary:
        started_at = datetime.now(UTC)
        enabled_roots = sorted((root for root in roots if root.enabled), key=lambda root: root.root_id)
        observations: dict[str, dict[str, SkillSnapshot]] = {}
        warnings: list[str] = []
        self._vectorization_warnings = []
        if self.vectorization is not None and getattr(self.embedding, "degraded_reason", None):
            self._vectorization_warnings.append(
                f"vectorizer_degraded: {self.embedding.degraded_reason}"
            )
        invalid = 0
        for root in enabled_roots:
            root_observations, root_warnings = self._observe(
                root, changed_paths, self._current_state(root)
            )
            observations[root.root_id] = root_observations
            warnings.extend(root_warnings)
            invalid += sum(
                item is not None and item.status is SkillStatus.INVALID
                for item in root_observations.values()
            )

        completed_at = datetime.now(UTC)
        revision = f"sync-{completed_at.strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:8]}"
        with self.repository.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for root in enabled_roots:
                    self._upsert_root(connection, root)
                added, updated, removed = self._apply(connection, enabled_roots, observations, changed_paths)
                warnings.extend(self._vectorization_warnings)
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
        self,
        root: LibraryRoot,
        changed_paths: list[Path] | None,
        current: dict[str, dict[str, str]],
    ) -> tuple[dict[str, SkillSnapshot | None], list[str]]:
        snapshots: dict[str, SkillSnapshot | None] = {}
        warnings: list[str] = []
        for path in self._skill_files(root, changed_paths):
            try:
                fingerprint = self._directory_fingerprint(path.parent)
                relative_path = path.relative_to(root.path).as_posix()
                identity = skill_id(root.provider, root.scope.value, relative_path)
                known = current.get(relative_path)
                current_vector_ready = self._current_vector_ready(known)
                if (
                    known is not None
                    and known["status"] == SkillStatus.ACTIVE.value
                    and self._fingerprints.get(path)
                    == (fingerprint, known["snapshot_id"])
                    and known.get("instruction_hash") != known.get("content_hash")
                    and current_vector_ready
                ):
                    snapshots[relative_path] = None
                    continue
                try:
                    parsed = parse_skill(
                        path.parent, provider=Provider(root.provider), scope=Scope(root.scope.value)
                    )
                    snapshot = SkillSnapshot(
                        snapshot_id=snapshot_id(identity, parsed.content_hash),
                        skill_id=identity,
                        root_id=root.root_id,
                        relative_path=relative_path,
                        name=parsed.name,
                        description=parsed.description,
                        body=parsed.body,
                        content_hash=parsed.content_hash,
                        instruction_hash=parsed.instruction_hash,
                        behavior_hash=parsed.behavior_hash,
                        execution_hash=parsed.execution_hash,
                        hash_algorithm_revision=parsed.hash_algorithm_revision,
                        license=parsed.license,
                        compatibility=parsed.compatibility,
                        metadata=parsed.metadata,
                        allowed_tools=parsed.allowed_tools,
                        tools=parsed.tools,
                        permissions=parsed.permissions,
                        environments=parsed.environments,
                        inputs=parsed.inputs,
                        outputs=parsed.outputs,
                        indexed_at=datetime.now(UTC),
                    )
                    snapshots[relative_path] = snapshot
                    self._fingerprints[path] = (fingerprint, snapshot.snapshot_id)
                except SkillParseError as error:
                    content_hash = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
                    snapshot = SkillSnapshot(
                        snapshot_id=snapshot_id(identity, content_hash),
                        skill_id=identity,
                        root_id=root.root_id,
                        relative_path=relative_path,
                        name=path.parent.name,
                        content_hash=content_hash,
                        instruction_hash=content_hash,
                        status=SkillStatus.INVALID,
                        indexed_at=datetime.now(UTC),
                        parse_error=str(error),
                    )
                    snapshots[relative_path] = snapshot
                    self._fingerprints[path] = (fingerprint, snapshot.snapshot_id)
            except OSError as error:
                warnings.append(f"cannot inspect {path}: {error}")
        return snapshots, warnings

    @staticmethod
    def _directory_fingerprint(skill_root: Path) -> tuple[tuple[str, int, int], ...]:
        """Return a deterministic metadata fingerprint for all safe Skill files."""
        resolved_root = skill_root.resolve()
        files: list[tuple[str, int, int]] = []
        for candidate in skill_root.rglob("*"):
            if ".git" in candidate.parts or candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve()
                resolved.relative_to(resolved_root)
                stat = candidate.stat()
            except (OSError, ValueError):
                continue
            files.append((candidate.relative_to(skill_root).as_posix(), stat.st_size, stat.st_mtime_ns))
        return tuple(sorted(files))

    def _current_state(self, root: LibraryRoot) -> dict[str, dict[str, str]]:
        with self.repository.database.connect() as connection:
            rows = connection.execute(
                """SELECT skills.relative_path, skills.status, skills.current_snapshot_id,
                          skill_snapshots.content_hash, skill_snapshots.instruction_hash,
                          skill_snapshots.behavior_hash, skill_snapshots.execution_hash,
                          skill_snapshots.hash_algorithm_revision
                   FROM skills
                   LEFT JOIN skill_snapshots ON skill_snapshots.snapshot_id = skills.current_snapshot_id
                   WHERE skills.root_id = ?""",
                (root.root_id,),
            ).fetchall()
        return {
            row["relative_path"]: {
                "status": row["status"],
                "snapshot_id": row["current_snapshot_id"],
                "content_hash": row["content_hash"],
                "instruction_hash": row["instruction_hash"],
                "behavior_hash": row["behavior_hash"],
                "execution_hash": row["execution_hash"],
                "hash_algorithm_revision": row["hash_algorithm_revision"],
            }
            for row in rows
        }

    @staticmethod
    def _skill_files(root: LibraryRoot, changed_paths: list[Path] | None) -> list[Path]:
        if changed_paths is None:
            try:
                return sorted(root.path.rglob("SKILL.md"), key=lambda path: path.as_posix())
            except OSError:
                return []
        selected: set[Path] = set()
        for changed in changed_paths:
            path = CatalogReconciler._changed_path(root, changed)
            try:
                path.relative_to(root.path.resolve())
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
        observations: dict[str, dict[str, SkillSnapshot | None]],
        changed_paths: list[Path] | None,
    ) -> tuple[int, int, int]:
        added = updated = removed = 0
        for root in roots:
            current = connection.execute(
                """SELECT skills.skill_id, skills.relative_path, skills.status, skills.current_snapshot_id AS snapshot_id,
                          skill_snapshots.content_hash, skill_snapshots.instruction_hash,
                          skill_snapshots.behavior_hash, skill_snapshots.execution_hash,
                          skill_snapshots.hash_algorithm_revision,
                          skill_snapshots.status AS snapshot_status
                   FROM skills JOIN skill_snapshots ON skills.current_snapshot_id = skill_snapshots.snapshot_id
                   WHERE skills.root_id = ?""",
                (root.root_id,),
            ).fetchall()
            previous = {row["relative_path"]: row for row in current}
            observed = observations[root.root_id]
            for relative_path, item in observed.items():
                if item is None:
                    continue
                before = previous.get(relative_path)
                same_content = before is not None and before["content_hash"] == item.content_hash and before[
                    "snapshot_status"
                ] == item.status.value and before["status"] == item.status.value and before[
                    "instruction_hash"
                ] == item.instruction_hash and before["behavior_hash"] == item.behavior_hash and before[
                    "execution_hash"
                ] == item.execution_hash
                if same_content:
                    if item.status is SkillStatus.ACTIVE and self.embedding is not None:
                        if self.vectorization is not None:
                            if not self.repository.has_segment_vectors(
                                item.snapshot_id,
                                self.vectorization.model_signature,
                                dimensions=self.vectorization.descriptor.dimensions,
                                backend_kind=self.vectorization.descriptor.kind,
                            ):
                                self._try_encode_segments(connection, item)
                        else:
                            vector_row = connection.execute(
                                "SELECT 1 FROM vectors WHERE snapshot_id = ? AND model = ?",
                                (item.snapshot_id, self.embedding.model_id),
                            ).fetchone()
                            if vector_row is None:
                                try:
                                    vector = self.embedding.encode([self._embedding_text(item)])[0]
                                    self._save_vector(connection, item, vector)
                                except (EmbeddingUnavailable, ValueError) as error:
                                    self._mark_vectorization_degraded(error)
                    continue
                if before is None:
                    added += 1
                else:
                    updated += 1
                self._upsert_snapshot(connection, item)
                if (
                    item.status is SkillStatus.ACTIVE
                    and self.embedding is not None
                    and (before is None or before["snapshot_id"] != item.snapshot_id)
                ):
                    if self.vectorization is not None:
                        self._try_encode_segments(connection, item)
                    else:
                        try:
                            vector = self.embedding.encode([self._embedding_text(item)])[0]
                            self._save_vector(connection, item, vector)
                        except (EmbeddingUnavailable, ValueError) as error:
                            self._mark_vectorization_degraded(error)
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
        skill_path = CatalogReconciler._normalized_path(root.path / relative_path)
        for changed in changed_paths:
            changed_path = CatalogReconciler._normalized_path(
                CatalogReconciler._changed_path(root, changed)
            )
            if changed_path == skill_path or changed_path == skill_path.parent:
                return True
        return False

    @staticmethod
    def _changed_path(root: LibraryRoot, changed: Path) -> Path:
        path = Path(changed)
        cwd_path = path.resolve(strict=False)
        try:
            cwd_path.relative_to(root.path.resolve())
            return cwd_path
        except ValueError:
            if not path.is_absolute():
                return (root.path / path).resolve(strict=False)
            return cwd_path

    @staticmethod
    def _normalized_path(path: Path) -> Path:
        return Path(os.path.normcase(str(path.resolve(strict=False))))

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
            """INSERT INTO skill_snapshots (snapshot_id, skill_id, root_id, relative_path, name,
               description, body, content_hash, status, tools_json, permissions_json, environments_json,
               inputs_json, outputs_json, indexed_at, parse_error, instruction_hash,
               behavior_hash, execution_hash, hash_algorithm_revision, license,
               compatibility, metadata_json, allowed_tools_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(snapshot_id) DO UPDATE SET
                   skill_id=excluded.skill_id, root_id=excluded.root_id,
                   relative_path=excluded.relative_path, name=excluded.name,
                   description=excluded.description, body=excluded.body,
                   content_hash=excluded.content_hash, status=excluded.status,
                   tools_json=excluded.tools_json, permissions_json=excluded.permissions_json,
                   environments_json=excluded.environments_json, inputs_json=excluded.inputs_json,
                   outputs_json=excluded.outputs_json, indexed_at=excluded.indexed_at,
                   parse_error=excluded.parse_error, instruction_hash=excluded.instruction_hash,
                   behavior_hash=excluded.behavior_hash, execution_hash=excluded.execution_hash,
                   hash_algorithm_revision=excluded.hash_algorithm_revision,
                   license=excluded.license, compatibility=excluded.compatibility,
                   metadata_json=excluded.metadata_json, allowed_tools_json=excluded.allowed_tools_json""",
            (item.snapshot_id, item.skill_id, item.root_id, item.relative_path, item.name, item.description,
             item.body, item.content_hash, item.status.value, json.dumps(item.tools, ensure_ascii=False),
             json.dumps(item.permissions, ensure_ascii=False), json.dumps(item.environments, ensure_ascii=False),
             json.dumps(item.inputs, ensure_ascii=False), json.dumps(item.outputs, ensure_ascii=False),
             item.indexed_at.isoformat(), item.parse_error, item.instruction_hash,
             item.behavior_hash, item.execution_hash, item.hash_algorithm_revision, item.license,
             item.compatibility, json.dumps(item.metadata, ensure_ascii=False),
             json.dumps(item.allowed_tools, ensure_ascii=False)),
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
        record = CatalogReconciler._record(item)
        return "\n".join(
            part for part in (activation_text(record), procedure_text(record)) if part
        )

    @staticmethod
    def _record(item: SkillSnapshot) -> SkillRecord:
        return SkillRecord(
            skill_id=item.skill_id,
            name=item.name,
            description=item.description,
            root_path=Path(item.relative_path).parent,
            body=item.body,
            content_hash=item.content_hash,
            instruction_hash=item.instruction_hash,
            license=item.license,
            compatibility=item.compatibility,
            metadata=item.metadata,
            allowed_tools=item.allowed_tools,
            tools=item.tools,
            permissions=item.permissions,
            environments=item.environments,
            inputs=item.inputs,
            outputs=item.outputs,
        )

    def _current_vector_ready(self, known: dict[str, str] | None) -> bool:
        if known is None or self.embedding is None:
            return self.embedding is None
        if self.vectorization is not None:
            return self.repository.has_segment_vectors(
                known["snapshot_id"],
                self.vectorization.model_signature,
                dimensions=self.vectorization.descriptor.dimensions,
                backend_kind=self.vectorization.descriptor.kind,
            )
        return self.repository.has_vector(known["snapshot_id"], self.embedding.model_id)

    def _encode_segments(self, connection: sqlite3.Connection, item: SkillSnapshot) -> None:
        assert self.vectorization is not None
        record = SkillRecord(
            skill_id=item.skill_id,
            name=item.name,
            description=item.description,
            root_path=Path(item.relative_path).parent,
            body=item.body,
            content_hash=item.content_hash,
            instruction_hash=item.instruction_hash,
            behavior_hash=item.behavior_hash,
            execution_hash=item.execution_hash,
            hash_algorithm_revision=item.hash_algorithm_revision,
            license=item.license,
            compatibility=item.compatibility,
            metadata=item.metadata,
            allowed_tools=item.allowed_tools,
            tools=item.tools,
            permissions=item.permissions,
            environments=item.environments,
            inputs=item.inputs,
            outputs=item.outputs,
        )
        sections = extract_skill_sections(record)
        encoded = self.vectorization.encode_record(record, sections)
        self.vectorization.replace_snapshot(
            item.snapshot_id,
            sections,
            encoded,
            connection=connection,
        )
        # Keep the v1 vectors table populated as a compatibility artifact for
        # historical reads and older integrations. New retrieval uses the
        # channel rows above and never mixes signatures implicitly.
        legacy_rows = [
            vector
            for channels in encoded.values.values()
            for channel in ("activation", "procedure", "constraint")
            for vector in channels.get(channel, ())
        ]
        if legacy_rows:
            self._save_vector(connection, item, legacy_rows[0])

    def _try_encode_segments(self, connection: sqlite3.Connection, item: SkillSnapshot) -> None:
        try:
            self._encode_segments(connection, item)
        except (EmbeddingUnavailable, ValueError) as error:
            # Keep the parsed snapshot transaction, but leave dense rows absent
            # so the analyzer can make the lexical fallback explicit.
            self._mark_vectorization_degraded(error)

    def _mark_vectorization_degraded(self, error: Exception) -> None:
        reason = f"vectorizer encode failed; using lexical analysis ({type(error).__name__})"
        if reason not in self._vectorization_warnings:
            self._vectorization_warnings.append(reason)
        if self.embedding is not None:
            self.embedding.degraded_reason = reason
            self.embedding.degraded_error = str(error)

    def _save_vector(self, connection: sqlite3.Connection, item: SkillSnapshot, vector) -> None:
        array = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(-1))
        connection.execute(
            """INSERT INTO vectors (snapshot_id, model, dimensions, content_hash, vector, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(snapshot_id, model) DO UPDATE SET
                   dimensions=excluded.dimensions,
                   content_hash=excluded.content_hash,
                   vector=excluded.vector,
                   created_at=excluded.created_at""",
            (item.snapshot_id, self.embedding.model_id, int(array.size), item.content_hash, array.tobytes(),
             datetime.now(UTC).isoformat()),
        )
