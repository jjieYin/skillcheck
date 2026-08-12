from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from skillcheck.catalog.models import LibraryRoot, SkillSnapshot

from .models import CandidateGroupSummary, Relation


@dataclass(frozen=True, order=True)
class GovernanceScopeKey:
    provider: str
    scope: str
    project_path: str
    root_id: str

    @classmethod
    def from_root(cls, root: LibraryRoot) -> GovernanceScopeKey:
        return cls(
            provider=root.provider.casefold(),
            scope=root.scope.value,
            project_path=str(root.project_path.resolve()) if root.project_path else "",
            root_id=root.root_id,
        )


class ScopeClassifier:
    """Classify identical Skills without conflating installation scopes."""

    def __init__(self, roots: Iterable[LibraryRoot] | Mapping[str, LibraryRoot]) -> None:
        root_values = roots.values() if isinstance(roots, Mapping) else roots
        self._scope_by_root = {
            root.root_id: GovernanceScopeKey.from_root(root) for root in root_values
        }

    def classify(self, snapshots: Iterable[SkillSnapshot]) -> list[CandidateGroupSummary]:
        by_hash: dict[str, list[SkillSnapshot]] = defaultdict(list)
        for snapshot in snapshots:
            by_hash[snapshot.content_hash].append(snapshot)

        groups: list[CandidateGroupSummary] = []
        for snapshots_with_hash in by_hash.values():
            by_scope: dict[GovernanceScopeKey, list[SkillSnapshot]] = defaultdict(list)
            for snapshot in snapshots_with_hash:
                by_scope[self._scope_by_root[snapshot.root_id]].append(snapshot)

            for members in by_scope.values():
                if len(members) > 1:
                    groups.append(self._group(Relation.EXACT_DUPLICATE, members))
            if len(by_scope) >= 2:
                groups.append(self._group(Relation.MIRRORED_COPY, snapshots_with_hash))

        return sorted(groups, key=lambda group: (group.relation.value, group.group_id))

    @staticmethod
    def _group(
        relation: Relation, snapshots: Iterable[SkillSnapshot]
    ) -> CandidateGroupSummary:
        member_skill_ids = sorted(snapshot.skill_id for snapshot in snapshots)
        digest = hashlib.sha256("|".join(member_skill_ids).encode("utf-8")).hexdigest()[:10]
        return CandidateGroupSummary(
            group_id=f"AG-{relation.value.lower()}-{digest}",
            relation=relation,
            member_skill_ids=member_skill_ids,
            requires_agent_judgment=False,
        )
