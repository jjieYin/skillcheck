from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np

from skillcheck.catalog.ids import root_id, skill_id, snapshot_id
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot, SkillStatus
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.core.audit import LibraryAuditor
from skillcheck.core.parser import SkillParseError, content_hash, parse_skill
from skillcheck.core.validators import BuiltinValidator
from skillcheck.mcp.runtime import McpRuntime
from skillcheck.models import Finding, Severity, SkillRecord
from skillcheck.sources import SourceLimits, stage_source

from .models import (
    AnalyzeMode,
    AnalyzeResult,
    AnalyzeSummary,
    CandidateGroupSummary,
    EvidencePage,
    EvidenceSkill,
    Relation,
    SourcePreflight,
)
from .repository import GovernanceRepository
from .scopes import ScopeClassifier

_PAGE_SIZE = 20
_BODY_LIMIT = 12_000
_RELATION_PRIORITY = {
    Relation.EXACT_DUPLICATE: 0,
    Relation.MIRRORED_COPY: 1,
    Relation.CONFLICT_CANDIDATE: 2,
    Relation.VARIANT_CANDIDATE: 3,
    Relation.HIGH_OVERLAP_CANDIDATE: 4,
    Relation.SECURITY_ISSUE: 5,
    Relation.QUALITY_ISSUE: 6,
}
_SENSITIVE_FIELD = re.compile(
    r"(?im)^([^\n:=]*?(?:token|api[_-]?key|secret|password)[^\n:=]*)\s*[:=]\s*.*$"
)
_CREDENTIAL = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{10,}|(?:api[_-]?key|token|secret|password)\s*=\s*['\"][^'\"]+['\"])",
    re.IGNORECASE,
)
_LEXICAL_TOKEN = re.compile(r"\w+", re.UNICODE)
_LEXICAL_DIMENSIONS = 128


class GovernanceAnalyzer:
    """Deterministic local analysis and bounded evidence retrieval.

    This boundary intentionally has no Agent, process, or network dependency.
    """

    def __init__(
        self,
        catalog: CatalogRepository,
        runtime: McpRuntime | None = None,
        *,
        staging_root: Path | str | None = None,
        source_limits: SourceLimits | None = None,
    ) -> None:
        self.catalog = catalog
        self.runtime = runtime
        self.repository = GovernanceRepository(catalog)
        self.staging_root = Path(staging_root or catalog.database.path.parent / "staging").expanduser()
        self.source_limits = source_limits or SourceLimits()

    def analyze(
        self,
        mode: AnalyzeMode | str,
        *,
        source: Path | str | None = None,
        scope: str = "all",
        limit: int = 20,
    ) -> AnalyzeResult:
        selected_mode = AnalyzeMode(mode)
        if selected_mode is AnalyzeMode.LIBRARY:
            if source is not None:
                raise ValueError("library analysis does not accept a source")
            return self.analyze_library(scope=scope, limit=limit)
        if source is None:
            raise ValueError("source analysis requires a staged local directory or ZIP file")
        return self.analyze_source(source, limit=limit)

    def analyze_library(self, *, scope: str = "all", limit: int | None = 20) -> AnalyzeResult:
        stale = self._sync_and_stale([])
        snapshots = self.catalog.list_current_skills()
        if limit is None:
            limit = max(1, len(snapshots))
        else:
            self._validate_limit(limit)
        return self._analyze(AnalyzeMode.LIBRARY, snapshots, self._revision(), stale, limit)

    def analyze_source(
        self, source: Path | str, *, scope: str = "all", limit: int = 20
    ) -> AnalyzeResult:
        self._validate_limit(limit)
        del scope
        self.staging_root.mkdir(parents=True, exist_ok=True)
        with stage_source(source, limits=self.source_limits, staging_parent=self.staging_root) as staged:
            root = staged.root
            source_hash = content_hash(root)
            source_snapshots = self._source_snapshots(root, source_hash)
            snapshots = [*source_snapshots, *self.catalog.list_current_skills()]
            result = self._analyze(
                AnalyzeMode.SOURCE,
                snapshots,
                source_hash,
                False,
                limit,
                lexical_fallback=True,
                source_skill_ids={item.skill_id for item in source_snapshots},
            )
            created_at = datetime.now(UTC)
            self.repository.save_source_preflight(
                SourcePreflight(
                    run_id=result.run_id,
                    source=str(source),
                    source_hash=source_hash,
                    created_at=created_at,
                    expires_at=created_at + timedelta(minutes=15),
                    deterministic_blockers=_source_security_findings(root),
                )
            )
            return result

    def evidence(
        self, run_id: str, group_id: str, page: int = 1, include_body: bool = False
    ) -> EvidencePage:
        if page < 1:
            raise ValueError("page must be at least 1")
        pending_before = self._pending_paths()
        self._sync_and_stale([])
        revision, members = self.repository.evidence_members(run_id, group_id)
        paths = self._member_paths(members)
        stale = any(_paths_overlap(pending, member) for pending in pending_before for member in paths)
        page_count = max(1, math.ceil(len(members) / _PAGE_SIZE))
        if page > page_count:
            raise ValueError("page exceeds available evidence")
        selected = members[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
        return EvidencePage(
            run_id=run_id,
            group_id=group_id,
            revision=revision,
            stale=stale,
            page=page,
            page_count=page_count,
            members=[self._evidence_skill(item, include_body) for item in selected],
            shared_capabilities=_shared_capabilities(members),
            different_capabilities=_different_capabilities(members),
        )

    def _analyze(
        self,
        mode: AnalyzeMode,
        snapshots: list[SkillSnapshot],
        revision: str,
        stale: bool,
        limit: int,
        *,
        lexical_fallback: bool = False,
        source_skill_ids: set[str] | None = None,
    ) -> AnalyzeResult:
        selected = self._select_snapshots(snapshots, limit, source_skill_ids)
        records = [self._record(item) for item in selected]
        findings = {item.skill_id: _snapshot_findings(item) for item in selected}
        vectors = self._vectors_for(selected, lexical_fallback=lexical_fallback)
        audit = LibraryAuditor(top_k=limit).audit(records, vectors, findings=findings)
        groups = [
            self._group(group)
            for group in audit.groups
            if group.relation != Relation.EXACT_DUPLICATE.value
        ]
        groups.extend(ScopeClassifier(self.catalog.list_roots()).classify(selected))
        groups.sort(key=lambda group: (
            _RELATION_PRIORITY[group.relation],
            -(group.similarity if group.similarity is not None else -1.0),
            group.group_id,
        ))
        run_id = f"run-{uuid4().hex}"
        by_skill = {item.skill_id: item for item in selected}
        self.repository.save_run(
            run_id,
            kind=mode.value,
            revision=revision,
            groups=groups,
            snapshots_by_skill=by_skill,
            findings=audit.findings,
        )
        return AnalyzeResult(
            run_id=run_id,
            mode=mode,
            revision=revision,
            stale=stale,
            summary=_summary(len(selected), groups),
            groups=groups,
            deterministic_findings=audit.findings,
            next_tool="skillcheck_evidence" if groups else None,
        )

    def _source_snapshots(self, root: Path, source_hash: str) -> list[SkillSnapshot]:
        snapshots: list[SkillSnapshot] = []
        source_root_id = root_id("staged", "source", source_hash)
        self.catalog.upsert_root(
            LibraryRoot(
                root_id=source_root_id,
                path=root.resolve(),
                provider="staged",
                scope=RootScope.CUSTOM,
                enabled=False,
            )
        )
        for path in sorted(root.rglob("SKILL.md")):
            try:
                record = parse_skill(path.parent)
            except SkillParseError:
                continue
            relative = path.relative_to(root).as_posix()
            identity = skill_id("staged", "source", f"{source_hash}/{relative}")
            snapshot = SkillSnapshot(
                snapshot_id=snapshot_id(identity, record.content_hash),
                skill_id=identity,
                root_id=source_root_id,
                relative_path=relative,
                name=record.name,
                description=record.description,
                body=record.body,
                content_hash=record.content_hash,
                tools=record.tools,
                permissions=record.permissions,
                environments=record.environments,
                inputs=record.inputs,
                outputs=record.outputs,
                indexed_at=datetime.now(UTC),
            )
            self.catalog.upsert_snapshot(snapshot)
            self.catalog.mark_missing(identity)
            snapshots.append(snapshot.model_copy(update={"status": SkillStatus.MISSING}))
        return snapshots

    def _vectors_for(
        self, snapshots: Iterable[SkillSnapshot], *, lexical_fallback: bool = False
    ) -> dict[str, object]:
        snapshots = list(snapshots)
        if lexical_fallback:
            return {item.skill_id: _lexical_vector(item) for item in snapshots}
        by_snapshot = {item.snapshot_id: item.skill_id for item in snapshots}
        vectors: dict[str, object] = {}
        for vector in self.catalog.get_vectors():
            skill = by_snapshot.get(vector.snapshot_id)
            if skill is not None and skill not in vectors:
                vectors[skill] = vector.vector
        return vectors

    @staticmethod
    def _select_snapshots(
        snapshots: list[SkillSnapshot], limit: int, source_skill_ids: set[str] | None
    ) -> list[SkillSnapshot]:
        ordered = sorted(snapshots, key=lambda item: item.skill_id)
        if not source_skill_ids:
            return ordered[:limit]
        sources = [item for item in ordered if item.skill_id in source_skill_ids][:limit]
        remaining = limit - len(sources)
        if remaining <= 0:
            return sources
        source_vectors = [_lexical_vector(item) for item in sources]
        catalog = [item for item in ordered if item.skill_id not in source_skill_ids]
        catalog.sort(
            key=lambda item: (-_max_similarity(_lexical_vector(item), source_vectors), item.skill_id)
        )
        return [*sources, *catalog[:remaining]]

    @staticmethod
    def _record(snapshot: SkillSnapshot) -> SkillRecord:
        return SkillRecord(
            skill_id=snapshot.skill_id,
            name=snapshot.name,
            description=snapshot.description,
            root_path=Path(snapshot.relative_path).parent,
            body=snapshot.body,
            content_hash=snapshot.content_hash,
            tools=snapshot.tools,
            permissions=snapshot.permissions,
            environments=snapshot.environments,
            inputs=snapshot.inputs,
            outputs=snapshot.outputs,
        )

    @staticmethod
    def _group(group) -> CandidateGroupSummary:
        relation = Relation(group.relation)
        similarity = _similarity(group.same_points)
        return CandidateGroupSummary(
            group_id=group.group_id,
            relation=relation,
            member_skill_ids=group.member_skill_ids,
            similarity=similarity,
            requires_agent_judgment=relation
            in {
                Relation.HIGH_OVERLAP_CANDIDATE,
                Relation.CONFLICT_CANDIDATE,
                Relation.VARIANT_CANDIDATE,
            },
        )

    def _member_paths(self, members: list[SkillSnapshot]) -> list[Path]:
        roots = {root.root_id: root.path for root in self.catalog.list_roots()}
        return [roots[item.root_id] / item.relative_path for item in members if item.root_id in roots]

    @staticmethod
    def _evidence_skill(snapshot: SkillSnapshot, include_body: bool) -> EvidenceSkill:
        body = _redact(snapshot.body[:_BODY_LIMIT]) if include_body else None
        return EvidenceSkill(
            skill_id=snapshot.skill_id,
            name=snapshot.name,
            description=snapshot.description,
            content_hash=snapshot.content_hash,
            tools=snapshot.tools,
            permissions=snapshot.permissions,
            environments=snapshot.environments,
            inputs=snapshot.inputs,
            outputs=snapshot.outputs,
            body=body,
        )

    def _sync_and_stale(self, paths: list[Path]) -> bool:
        if self.runtime is None:
            return False
        stale = self.runtime.is_stale(paths) if paths else False
        self.runtime.before_query()
        return stale

    def _pending_paths(self) -> set[Path]:
        if self.runtime is None:
            return set()
        return set(self.runtime.pending_paths())

    def _revision(self) -> str:
        if self.runtime is not None:
            status = getattr(self.runtime, "status", lambda: None)()
            if status is not None and status.revision:
                return status.revision
        with self.catalog.database.connect() as connection:
            row = connection.execute(
                "SELECT revision FROM sync_events ORDER BY completed_at DESC, event_id DESC LIMIT 1"
            ).fetchone()
        return row["revision"] if row else "catalog"

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

def _snapshot_findings(snapshot: SkillSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    if not snapshot.description:
        findings.append(_finding("FMT002", Severity.MEDIUM, "Skill is missing a description."))
    if len(snapshot.body.strip()) < 20:
        findings.append(_finding("QLT001", Severity.LOW, "Skill body is too short."))
    if _CREDENTIAL.search(snapshot.body):
        findings.append(_finding("SEC002", Severity.HIGH, "Skill appears to contain a hardcoded credential."))
    return findings


def _source_security_findings(root: Path) -> list[Finding]:
    """Return every built-in deterministic security finding from the staged source."""

    validator = BuiltinValidator()
    findings: list[Finding] = []
    for marker in sorted(root.rglob("SKILL.md"), key=lambda item: item.as_posix()):
        try:
            record = parse_skill(marker.parent)
        except SkillParseError as exc:
            findings.append(
                _finding("SEC006", Severity.HIGH, f"Skill cannot be parsed safely: {exc}")
            )
            continue
        findings.extend(
            finding for finding in validator.scan(marker.parent, record) if finding.rule_id.startswith("SEC")
        )
    return list({(item.rule_id, item.message): item for item in findings}.values())


def _finding(rule_id: str, severity: Severity, message: str) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message=message, remediation="Review the local Skill.")


def _summary(skills_considered: int, groups: list[CandidateGroupSummary]) -> AnalyzeSummary:
    counts = {relation: 0 for relation in Relation}
    for group in groups:
        counts[group.relation] += 1
    return AnalyzeSummary(
        skills_considered=skills_considered,
        exact_duplicates=counts[Relation.EXACT_DUPLICATE],
        overlap_candidates=counts[Relation.HIGH_OVERLAP_CANDIDATE],
        conflict_candidates=counts[Relation.CONFLICT_CANDIDATE],
        variant_candidates=counts[Relation.VARIANT_CANDIDATE],
        quality_issues=counts[Relation.QUALITY_ISSUE],
        security_issues=counts[Relation.SECURITY_ISSUE],
    )


def _similarity(evidence: list[str]) -> float | None:
    match = next((re.search(r"cosine similarity=(0(?:\.\d+)?|1(?:\.0+)?)", item) for item in evidence), None)
    return float(match.group(1)) if match else None


def _redact(text: str) -> str:
    return _SENSITIVE_FIELD.sub(lambda match: f"{match.group(1)}: [REDACTED]", text)


def _lexical_vector(snapshot: SkillSnapshot) -> np.ndarray:
    vector = np.zeros(_LEXICAL_DIMENSIONS, dtype=np.float32)
    text = f"{snapshot.name} {snapshot.description} {snapshot.body}".casefold()
    for token in _LEXICAL_TOKEN.findall(text):
        index = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:4], "big") % _LEXICAL_DIMENSIONS
        vector[index] += 1.0
    return vector


def _max_similarity(vector: np.ndarray, candidates: list[np.ndarray]) -> float:
    norm = float(np.linalg.norm(vector))
    if norm == 0 or not candidates:
        return 0.0
    return max(
        (float(np.dot(vector, candidate) / (norm * candidate_norm)) if candidate_norm else 0.0)
        for candidate in candidates
        for candidate_norm in [float(np.linalg.norm(candidate))]
    )


def _paths_overlap(first: Path, second: Path) -> bool:
    first_path = Path(first).expanduser().resolve(strict=False)
    second_path = Path(second).expanduser().resolve(strict=False)
    return first_path == second_path or first_path in second_path.parents or second_path in first_path.parents


def _shared_capabilities(members: list[SkillSnapshot]) -> list[str]:
    if not members:
        return []
    capabilities = [set(member.tools + member.permissions + member.environments) for member in members]
    return sorted(set.intersection(*capabilities))


def _different_capabilities(members: list[SkillSnapshot]) -> list[str]:
    capabilities = [set(member.tools + member.permissions + member.environments) for member in members]
    return sorted(set.union(*capabilities) - set.intersection(*capabilities)) if capabilities else []
