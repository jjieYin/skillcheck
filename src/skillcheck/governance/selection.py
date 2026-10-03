"""Deterministic selection of catalog snapshots for governance analysis."""

from __future__ import annotations

import os
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from skillcheck.catalog.models import LibraryRoot, RootScope, SkillSnapshot


class AnalysisScope(StrEnum):
    ALL = "all"
    GLOBAL = "global"
    PROJECT = "project"
    CUSTOM = "custom"


class ScopeSelector:
    """Apply the requested analysis scope without widening it implicitly."""

    def select_library(
        self,
        snapshots: Iterable[SkillSnapshot],
        roots: Iterable[LibraryRoot],
        scope: AnalysisScope | str,
        *,
        project_path: Path | str | None = None,
    ) -> list[SkillSnapshot]:
        selected_scope = self._scope(scope)
        roots_by_id = {root.root_id: root for root in roots if root.enabled}
        allowed_roots = {
            root.root_id
            for root in roots_by_id.values()
            if self._matches(root, selected_scope, project_path)
        }
        return sorted(
            (snapshot for snapshot in snapshots if snapshot.root_id in allowed_roots),
            key=lambda item: item.skill_id,
        )

    def select_catalog_for_source(
        self,
        snapshots: list[SkillSnapshot],
        roots: list[LibraryRoot],
        scope: AnalysisScope | str,
        *,
        project_path: Path | str | None = None,
    ) -> list[SkillSnapshot]:
        """Select only local catalog snapshots; callers always prepend staged input."""

        return self.select_library(snapshots, roots, scope, project_path=project_path)

    @staticmethod
    def _scope(scope: AnalysisScope | str) -> AnalysisScope:
        try:
            return AnalysisScope(scope)
        except (TypeError, ValueError) as error:
            allowed = ", ".join(item.value for item in AnalysisScope)
            raise ValueError(f"scope must be one of: {allowed}") from error

    @classmethod
    def _matches(
        cls,
        root: LibraryRoot,
        scope: AnalysisScope,
        project_path: Path | str | None,
    ) -> bool:
        if scope is AnalysisScope.ALL:
            return True
        if scope is AnalysisScope.GLOBAL:
            return root.scope is RootScope.GLOBAL
        if scope is AnalysisScope.CUSTOM:
            return root.scope is RootScope.CUSTOM
        if project_path is None:
            raise ValueError("project scope requires a current project path")
        if root.scope is not RootScope.PROJECT or root.project_path is None:
            return False
        return cls._normalize(root.project_path) == cls._normalize(project_path)

    @staticmethod
    def _normalize(path: Path | str) -> str:
        return os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))
