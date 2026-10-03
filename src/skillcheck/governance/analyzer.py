from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from skillcheck.catalog.ids import root_id, skill_id, snapshot_id
from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot, SkillStatus
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.core.audit import LibraryAuditor
from skillcheck.core.candidates import legacy_channel_vectors
from skillcheck.core.decisions import RuleDecisionEngine
from skillcheck.core.parser import SkillParseError, content_hash, parse_skill
from skillcheck.core.sections import extract_skill_sections
from skillcheck.core.validation import CompositeSkillValidator
from skillcheck.core.validators import BuiltinValidator
from skillcheck.governance.policy import GovernancePolicy
from skillcheck.mcp.runtime import McpRuntime
from skillcheck.models import Finding, Severity, SkillRecord
from skillcheck.skillspector import SkillSpectorAdapter
from skillcheck.sources import SourceLimits, stage_source
from skillcheck.vectorization import ChannelVectors, VectorizationService

from .models import (
    AnalyzeMode,
    AnalyzeResult,
    AnalyzeSummary,
    CandidateGroupSummary,
    EvidencePage,
    EvidenceSkill,
    Relation,
    SkillFinding,
    SourcePreflight,
)
from .repository import EvidenceMember, GovernanceRepository
from .scopes import ScopeClassifier
from .selection import AnalysisScope, ScopeSelector

_PAGE_SIZE = 20
_BODY_LIMIT = 12_000
_RELATION_PRIORITY = {
    Relation.EXACT_DUPLICATE: 0,
    Relation.MIRRORED_COPY: 1,
    Relation.BEHAVIOR_DUPLICATE_CANDIDATE: 2,
    Relation.IMPLEMENTATION_VARIANT_CANDIDATE: 3,
    Relation.CONFLICT_CANDIDATE: 4,
    Relation.CONSTRAINT_MISMATCH_CANDIDATE: 5,
    Relation.HIGH_OVERLAP_CANDIDATE: 6,
    Relation.CONTAINMENT_CANDIDATE: 7,
    Relation.VARIANT_CANDIDATE: 8,
    Relation.MANUAL_REVIEW: 9,
    Relation.SECURITY_ISSUE: 10,
    Relation.QUALITY_ISSUE: 11,
}
_SENSITIVE_FIELD = re.compile(
    r"(?im)^([^\n:=]*?(?:token|api[_-]?key|secret|password)[^\n:=]*)\s*[:=]\s*.*$"
)
_CREDENTIAL = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{10,}|(?:api[_-]?key|token|secret|password)\s*=\s*['\"][^'\"]+['\"])",
    re.IGNORECASE,
)
TriggerSource = Literal["explicit_user", "agent_intent", "tool_chain", "cli"]
_TRIGGER_SOURCES = {"explicit_user", "agent_intent", "tool_chain", "cli"}


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
        policy: GovernancePolicy | None = None,
        validator: CompositeSkillValidator | None = None,
        vectorization: VectorizationService | None = None,
    ) -> None:
        self.catalog = catalog
        self.runtime = runtime
        self.repository = GovernanceRepository(catalog)
        self.staging_root = Path(staging_root or catalog.database.path.parent / "staging").expanduser()
        self.source_limits = source_limits or SourceLimits()
        self.policy = policy or GovernancePolicy.default()
        self.vectorization = vectorization
        self._source_channel_vectors: dict[str, ChannelVectors] = {}
        self.validator = validator or CompositeSkillValidator(
            BuiltinValidator(), _external_validator(self.policy.security)
        )
        self.selector = ScopeSelector()

    def analyze(
        self,
        mode: AnalyzeMode | str,
        *,
        source: Path | str | None = None,
        scope: str = "all",
        trigger_source: TriggerSource = "agent_intent",
    ) -> AnalyzeResult:
        self._validate_trigger_source(trigger_source)
        selected_mode = AnalyzeMode(mode)
        if selected_mode is AnalyzeMode.LIBRARY:
            if source is not None:
                raise ValueError("library analysis does not accept a source")
            return self.analyze_library(scope=scope, trigger_source=trigger_source)
        if source is None:
            raise ValueError("source analysis requires a staged local directory or ZIP file")
        return self.analyze_source(source, scope=scope, trigger_source=trigger_source)

    def analyze_library(
        self,
        *,
        scope: str = "all",
        trigger_source: TriggerSource = "agent_intent",
    ) -> AnalyzeResult:
        self._validate_trigger_source(trigger_source)
        stale = self._sync_and_stale([])
        snapshots = self.catalog.list_current_skills()
        snapshots = self.selector.select_library(
            snapshots,
            self.catalog.list_roots(),
            scope,
            project_path=self.policy.project_path,
        )
        return self._analyze(
            AnalyzeMode.LIBRARY,
            snapshots,
            self._revision(),
            stale,
            scope=scope,
            trigger_source=trigger_source,
        )

    def analyze_source(
        self,
        source: Path | str,
        *,
        scope: str = "all",
        trigger_source: TriggerSource = "agent_intent",
    ) -> AnalyzeResult:
        self._validate_trigger_source(trigger_source)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        with stage_source(source, limits=self.source_limits, staging_parent=self.staging_root) as staged:
            root = staged.root
            source_hash = content_hash(root)
            self._source_channel_vectors = {}
            source_snapshots = self._source_snapshots(root, source_hash)
            catalog_snapshots = self.selector.select_catalog_for_source(
                self.catalog.list_current_skills(),
                self.catalog.list_roots(),
                scope,
                project_path=self.policy.project_path,
            )
            snapshots = [*source_snapshots, *catalog_snapshots]
            result = self._analyze(
                AnalyzeMode.SOURCE,
                snapshots,
                source_hash,
                False,
                scope=scope,
                trigger_source=trigger_source,
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
                    deterministic_blockers=_source_security_findings(root, self.validator),
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
        snapshots = [member.snapshot for member in members]
        stale = any(_paths_overlap(pending, member) for pending in pending_before for member in paths)
        pair_evidence = self.repository.evidence_pair_evidence(run_id, group_id)
        page_count = max(
            1,
            math.ceil(len(members) / _PAGE_SIZE),
            math.ceil(len(pair_evidence) / _PAGE_SIZE),
        )
        if page > page_count:
            raise ValueError("page exceeds available evidence")
        selected = members[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
        pair_evidence = pair_evidence[(page - 1) * _PAGE_SIZE : page * _PAGE_SIZE]
        return EvidencePage(
            run_id=run_id,
            group_id=group_id,
            revision=revision,
            stale=stale,
            page=page,
            page_count=page_count,
            members=[self._evidence_skill(item, include_body) for item in selected],
            shared_capabilities=_shared_capabilities(snapshots),
            different_capabilities=_different_capabilities(snapshots),
            pair_evidence=pair_evidence,
        )

    def _analyze(
        self,
        mode: AnalyzeMode,
        snapshots: list[SkillSnapshot],
        revision: str,
        stale: bool,
        *,
        scope: AnalysisScope | str,
        trigger_source: TriggerSource,
        source_skill_ids: set[str] | None = None,
    ) -> AnalyzeResult:
        selected = snapshots
        roots = {root.root_id: root for root in self.catalog.list_roots()}
        records = [self._record(item, roots.get(item.root_id)) for item in selected]
        findings = {
            item.skill_id: self.validator.scan(Path(record.root_path), record)
            for item, record in zip(selected, records, strict=True)
        }
        vectors = self._vectors_for(selected)
        sections = {record.skill_id: extract_skill_sections(record) for record in records}
        channel_vectors = self._channel_vectors_for(selected)
        if channel_vectors is None and vectors:
            channel_vectors = legacy_channel_vectors(records, vectors)
        audit = LibraryAuditor(
            top_k=self.policy.thresholds.top_k,
            decision_engine=RuleDecisionEngine(self.policy.thresholds),
        ).audit(
            records,
            vectors,
            findings=findings,
            source_skill_ids=source_skill_ids,
            # Sections are the deterministic v2 baseline. Dense vectors are
            # optional evidence and must not switch analysis back to the v1
            # whole-document retriever when they are unavailable.
            sections=sections,
            channel_vectors=channel_vectors,
            vectorizer_kind=(
                channel_vectors.descriptor.kind if channel_vectors is not None else "lexical_hash"
            ),
            vectorizer_descriptor=(
                channel_vectors.descriptor.__dict__
                if channel_vectors is not None
                else (
                    self.vectorization.descriptor.__dict__
                    if self.vectorization is not None
                    else (self.policy.descriptor.__dict__ if self.policy.descriptor is not None else None)
                )
            ),
            vectorizer_signature=(
                self.vectorization.model_signature
                if self.vectorization is not None
                else self.policy.embedding_signature
            ),
            threshold_profile=self.policy.threshold_profile,
            semantic_thresholds_calibrated=self.policy.semantic_thresholds_calibrated,
            vectorizer_degraded=(
                getattr(self.vectorization.backend, "degraded_reason", None)
                if self.vectorization is not None
                else None
            ),
        )
        # Keep the legacy overlap group discoverable for callers that still
        # use the pre-relation taxonomy.  The behavior-duplicate relation is
        # the canonical result; this compatibility alias is deliberately
        # derived from the same pair evidence and never changes the decision.
        compatibility_groups = []
        for group in audit.groups:
            if group.relation != Relation.BEHAVIOR_DUPLICATE_CANDIDATE.value:
                continue
            compatibility_groups.append(
                group.model_copy(
                    update={
                        "group_id": f"{group.group_id}-compat-overlap",
                        "relation": Relation.HIGH_OVERLAP_CANDIDATE.value,
                        "pair_evidence": [
                            item.model_copy(
                                update={"relation": Relation.HIGH_OVERLAP_CANDIDATE.value}
                            )
                            for item in group.pair_evidence
                        ],
                    }
                )
            )
        audit.groups.extend(compatibility_groups)
        skill_findings = [
            SkillFinding(skill_id=skill_id, finding=finding)
            for skill_id in sorted(findings)
            for finding in findings[skill_id]
        ]
        groups = [
            self._group(group)
            for group in audit.groups
            if group.relation != Relation.EXACT_DUPLICATE.value
        ]
        pair_evidence_by_group = {
            self._group(group).group_id: group.pair_evidence
            for group in audit.groups
            if group.pair_evidence
        }
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
            skill_findings=skill_findings,
            pair_evidence=pair_evidence_by_group,
            policy_parameters={
                "thresholds": self.policy.thresholds.model_dump(mode="json"),
                "embedding_signature": self.policy.embedding_signature,
                "security": self.policy.security.model_dump(mode="json"),
                "fingerprint_revision": "2",
                "section_revision": "1",
                "feature_revision": "2",
                "vectorizer_descriptor": (
                    self.policy.descriptor.__dict__ if self.policy.descriptor is not None else None
                ),
                "vectorizer_locality": (
                    self.policy.descriptor.locality if self.policy.descriptor is not None else None
                ),
                "threshold_profile": self.policy.threshold_profile,
                "semantic_thresholds_calibrated": self.policy.semantic_thresholds_calibrated,
            },
            scope=str(scope),
            trigger_source=trigger_source,
        )
        return AnalyzeResult(
            run_id=run_id,
            mode=mode,
            revision=revision,
            stale=stale,
            summary=_summary(len(selected), groups, self._sync_groups(), audit.findings),
            groups=groups,
            deterministic_findings=audit.findings,
            skill_findings=skill_findings,
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
                instruction_hash=record.instruction_hash,
                behavior_hash=record.behavior_hash,
                execution_hash=record.execution_hash,
                hash_algorithm_revision=record.hash_algorithm_revision,
                license=record.license,
                compatibility=record.compatibility,
                metadata=record.metadata,
                allowed_tools=record.allowed_tools,
                tools=record.tools,
                permissions=record.permissions,
                environments=record.environments,
                inputs=record.inputs,
                outputs=record.outputs,
                indexed_at=datetime.now(UTC),
            )
            self.catalog.upsert_snapshot(snapshot)
            self.catalog.mark_missing(identity)
            if self.vectorization is not None:
                source_record = self._record(snapshot)
                try:
                    self._source_channel_vectors[snapshot.skill_id] = self.vectorization.encode_record(
                        source_record,
                        extract_skill_sections(source_record),
                    )
                except (ValueError, RuntimeError) as error:
                    self._mark_vectorization_degraded(error)
            snapshots.append(snapshot.model_copy(update={"status": SkillStatus.MISSING}))
        return snapshots

    def _vectors_for(
        self, snapshots: Iterable[SkillSnapshot]
    ) -> dict[str, object]:
        snapshots = list(snapshots)
        by_snapshot = {item.snapshot_id: item.skill_id for item in snapshots}
        vectors: dict[str, object] = {}
        model_signature = (
            self.vectorization.model_signature
            if self.vectorization is not None
            else self.policy.embedding_signature
        )
        for vector in self.catalog.get_vectors(model_signature):
            skill = by_snapshot.get(vector.snapshot_id)
            if skill is not None and skill not in vectors:
                vectors[skill] = vector.vector
        return vectors

    def _channel_vectors_for(
        self, snapshots: Iterable[SkillSnapshot]
    ) -> ChannelVectors | None:
        if self.vectorization is None:
            return None
        snapshots = list(snapshots)
        values: dict[str, dict[str, tuple[object, ...]]] = {
            skill_id: {
                channel: tuple(vectors)
                for channel, vectors in encoded.values.get(skill_id, {}).items()
            }
            for skill_id, encoded in self._source_channel_vectors.items()
            if skill_id in {snapshot.skill_id for snapshot in snapshots}
        }
        snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
        # The expected hashes are built from the same parsed sections that
        # drive lexical retrieval; use a local record reconstruction so a
        # stale row cannot be silently paired with a new body.
        expected_hashes = {}
        for snapshot in snapshots:
            skill_id = snapshot.skill_id
            record = self._record(snapshot)
            expected_hashes[snapshot.snapshot_id] = self.vectorization.expected_text_hashes(
                record,
                extract_skill_sections(record),
            )
        loaded = self.vectorization.load(snapshot_ids, expected_text_hashes=expected_hashes)
        by_snapshot = {snapshot.snapshot_id: snapshot.skill_id for snapshot in snapshots}
        for loaded_snapshot_id, channels in loaded.items():
            skill_id = by_snapshot.get(loaded_snapshot_id)
            if skill_id is not None:
                values[skill_id] = {
                    channel: tuple(vectors) for channel, vectors in channels.items()
                }
        if not values:
            return None
        return ChannelVectors(descriptor=self.vectorization.descriptor, values=values)

    def _mark_vectorization_degraded(self, error: Exception) -> None:
        reason = f"vectorizer encode failed; using lexical analysis ({type(error).__name__})"
        self.vectorization.backend.degraded_reason = reason
        self.vectorization.backend.degraded_error = str(error)

    @staticmethod
    def _record(snapshot: SkillSnapshot, root: LibraryRoot | None = None) -> SkillRecord:
        skill_root = (
            root.path / Path(snapshot.relative_path).parent
            if root is not None
            else Path(snapshot.relative_path).parent
        )
        return SkillRecord(
            skill_id=snapshot.skill_id,
            name=snapshot.name,
            description=snapshot.description,
            root_path=skill_root,
            body=snapshot.body,
            content_hash=snapshot.content_hash,
            instruction_hash=snapshot.instruction_hash,
            behavior_hash=snapshot.behavior_hash,
            execution_hash=snapshot.execution_hash,
            hash_algorithm_revision=snapshot.hash_algorithm_revision,
            license=snapshot.license,
            compatibility=snapshot.compatibility,
            metadata=snapshot.metadata,
            allowed_tools=snapshot.allowed_tools,
            tools=snapshot.tools,
            permissions=snapshot.permissions,
            environments=snapshot.environments,
            inputs=snapshot.inputs,
            outputs=snapshot.outputs,
        )

    @staticmethod
    def _group(group) -> CandidateGroupSummary:
        relation = Relation(group.relation)
        similarity = (
            group.mean_similarity
            if getattr(group, "mean_similarity", None) is not None
            else _similarity(group.same_points)
        )
        return CandidateGroupSummary(
            group_id=group.group_id,
            relation=relation,
            member_skill_ids=group.member_skill_ids,
            similarity=similarity,
            min_similarity=getattr(group, "min_similarity", None),
            mean_similarity=getattr(group, "mean_similarity", None),
            max_similarity=getattr(group, "max_similarity", None),
            requires_agent_judgment=relation
            in {
                Relation.HIGH_OVERLAP_CANDIDATE,
                Relation.BEHAVIOR_DUPLICATE_CANDIDATE,
                Relation.IMPLEMENTATION_VARIANT_CANDIDATE,
                Relation.CONTAINMENT_CANDIDATE,
                Relation.CONSTRAINT_MISMATCH_CANDIDATE,
                Relation.CONFLICT_CANDIDATE,
                Relation.VARIANT_CANDIDATE,
                Relation.MANUAL_REVIEW,
            },
        )

    @staticmethod
    def _member_paths(members: list[EvidenceMember]) -> list[Path]:
        return [Path(item.root_path) / item.snapshot.relative_path for item in members]

    @staticmethod
    def _evidence_skill(member: EvidenceMember, include_body: bool) -> EvidenceSkill:
        snapshot = member.snapshot
        body = _redact(snapshot.body[:_BODY_LIMIT]) if include_body else None
        return EvidenceSkill(
            skill_id=snapshot.skill_id,
            snapshot_id=snapshot.snapshot_id,
            provider=member.provider,
            scope=member.scope,
            project_path=member.project_path,
            root_path=member.root_path,
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

    @staticmethod
    def _validate_trigger_source(value: str) -> None:
        if value not in _TRIGGER_SOURCES:
            allowed = ", ".join(sorted(_TRIGGER_SOURCES))
            raise ValueError(f"trigger_source must be one of: {allowed}")

    def _sync_groups(self):
        """Refresh monitor-only groups before reporting their current drift state."""
        from .sync_groups import SyncGroupService

        return SyncGroupService(self.repository).list()

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

def _snapshot_findings(snapshot: SkillSnapshot) -> list[Finding]:
    findings: list[Finding] = []
    if not snapshot.description:
        findings.append(_finding("FMT002", Severity.MEDIUM, "Skill is missing a description."))
    if len(snapshot.body.strip()) < 20:
        findings.append(_finding("QLT001", Severity.LOW, "Skill body is too short."))
    if _CREDENTIAL.search(snapshot.body):
        findings.append(_finding("SEC002", Severity.HIGH, "Skill appears to contain a hardcoded credential."))
    return findings


def _source_security_findings(
    root: Path, validator: CompositeSkillValidator | None = None
) -> list[Finding]:
    """Return every built-in deterministic security finding from the staged source."""

    validator = validator or CompositeSkillValidator(BuiltinValidator())
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
            finding
            for finding in validator.scan(marker.parent, record)
            if finding.rule_id.startswith("SEC")
        )
    return list({(item.rule_id, item.message): item for item in findings}.values())


def _finding(rule_id: str, severity: Severity, message: str) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message=message, remediation="Review the local Skill.")


def _external_validator(security) -> SkillSpectorAdapter | None:
    if not security.enabled or not security.skill_spector_command:
        return None
    return SkillSpectorAdapter(
        command=security.skill_spector_command,
        timeout_seconds=security.timeout_seconds,
    )


def _summary(
    skills_considered: int,
    groups: list[CandidateGroupSummary],
    sync_groups,
    findings: list[Finding],
) -> AnalyzeSummary:
    counts = {relation: 0 for relation in Relation}
    for group in groups:
        counts[group.relation] += 1
    return AnalyzeSummary(
        skills_considered=skills_considered,
        exact_duplicates=counts[Relation.EXACT_DUPLICATE],
        mirrored_copy_groups=counts[Relation.MIRRORED_COPY],
        sync_groups_total=len(sync_groups),
        sync_groups_drifted=sum(group.status.value == "DRIFTED" for group in sync_groups),
        overlap_candidates=counts[Relation.HIGH_OVERLAP_CANDIDATE],
        behavior_duplicate_candidates=counts[Relation.BEHAVIOR_DUPLICATE_CANDIDATE],
        implementation_variant_candidates=counts[Relation.IMPLEMENTATION_VARIANT_CANDIDATE],
        containment_candidates=counts[Relation.CONTAINMENT_CANDIDATE],
        constraint_mismatch_candidates=counts[Relation.CONSTRAINT_MISMATCH_CANDIDATE],
        conflict_candidates=counts[Relation.CONFLICT_CANDIDATE],
        variant_candidates=counts[Relation.VARIANT_CANDIDATE],
        quality_issues=sum(1 for finding in findings if not finding.rule_id.upper().startswith("SEC")),
        security_issues=sum(1 for finding in findings if finding.rule_id.upper().startswith("SEC")),
    )


def _similarity(evidence: list[str]) -> float | None:
    match = next((re.search(r"cosine similarity=(0(?:\.\d+)?|1(?:\.0+)?)", item) for item in evidence), None)
    return float(match.group(1)) if match else None


def _redact(text: str) -> str:
    return _SENSITIVE_FIELD.sub(lambda match: f"{match.group(1)}: [REDACTED]", text)


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
