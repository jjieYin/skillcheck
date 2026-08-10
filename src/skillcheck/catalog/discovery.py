"""Discover supported local Skill library roots."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from skillcheck.catalog.ids import root_id
from skillcheck.catalog.models import LibraryRoot, RootScope

_PROVIDERS = (
    ("codex", ".codex", "skills"),
    ("agents", ".agents", "skills"),
    ("claude", ".claude", "skills"),
    ("cursor", ".cursor", "rules"),
)


def discover_library_roots(
    home: Path | str,
    project: Path | str,
    custom_paths: Iterable[Path | str] = (),
) -> list[LibraryRoot]:
    """Return existing supported Skill roots in a deterministic order."""
    home_path = Path(home).expanduser()
    project_path = Path(project).expanduser().resolve()
    candidates: list[tuple[Path, str, RootScope, Path | None]] = []
    for provider, directory, leaf in _PROVIDERS:
        candidates.append((home_path / directory / leaf, provider, RootScope.GLOBAL, None))
    for provider, directory, leaf in _PROVIDERS:
        candidates.append(
            (project_path / directory / leaf, provider, RootScope.PROJECT, project_path)
        )
    candidates.extend(
        (Path(path).expanduser(), "custom", RootScope.CUSTOM, None) for path in custom_paths
    )

    roots: list[LibraryRoot] = []
    seen: set[str] = set()
    for candidate, provider, scope, root_project_path in candidates:
        if not candidate.is_dir():
            continue
        path = candidate.resolve()
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        roots.append(
            LibraryRoot(
                root_id=root_id(provider, scope.value, path),
                path=path,
                provider=provider,
                scope=scope,
                project_path=root_project_path,
            )
        )
    return roots
