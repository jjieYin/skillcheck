from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from skillcheck.config import AppConfig
from skillcheck.core.parser import SkillParseError, parse_skill
from skillcheck.models import Provider, Scope, SkillRecord


@dataclass(frozen=True)
class ProviderPath:
    provider: Provider
    path: Path
    scope: Scope


@dataclass(frozen=True)
class DiscoveredInstall:
    skill: SkillRecord
    provider_path: ProviderPath

    @property
    def root_path(self) -> Path:
        return self.skill.root_path


@dataclass
class Inventory:
    installs: list[DiscoveredInstall] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    hash_duplicate_groups: list[list[SkillRecord]] = field(default_factory=list)
    name_groups: dict[str, list[SkillRecord]] = field(default_factory=dict)

    @property
    def unique_skills(self) -> list[SkillRecord]:
        return [install.skill for install in self.installs]

    @property
    def installation_count(self) -> int:
        return len(self.installs)


def default_provider_paths(home: Path | str, cwd: Path | str | None = None) -> list[ProviderPath]:
    home = Path(home).expanduser().resolve()
    project = Path(cwd or Path.cwd()).expanduser().resolve()
    entries = [
        (Provider.CODEX, home / ".codex" / "skills", Scope.GLOBAL),
        (Provider.AGENTS, home / ".agents" / "skills", Scope.GLOBAL),
        (Provider.CLAUDE, home / ".claude" / "skills", Scope.GLOBAL),
        (Provider.CURSOR, home / ".cursor" / "rules", Scope.GLOBAL),
        (Provider.CODEX, project / ".codex" / "skills", Scope.PROJECT),
        (Provider.AGENTS, project / ".agents" / "skills", Scope.PROJECT),
        (Provider.CLAUDE, project / ".claude" / "skills", Scope.PROJECT),
        (Provider.CURSOR, project / ".cursor" / "rules", Scope.PROJECT),
    ]
    result: list[ProviderPath] = []
    seen: set[str] = set()
    for provider, path, scope in entries:
        key = _path_key(path)
        if key not in seen:
            seen.add(key)
            result.append(ProviderPath(provider, path, scope))
    return result


def discover_skills(config: AppConfig, cwd: Path | str | None = None) -> Inventory:
    cwd_path = Path(cwd or Path.cwd()).expanduser().resolve()
    home = _infer_home(config)
    provider_paths = default_provider_paths(home, cwd_path)
    configured_paths = [*config.scan_paths, *config.extra_paths]
    provider_by_path = {_path_key(item.path): item for item in provider_paths}
    candidates: list[ProviderPath] = []
    seen_roots: set[str] = set()
    for configured in configured_paths:
        path = Path(configured).expanduser()
        provider_path = _ownership_for(path, provider_paths, provider_by_path, cwd_path)
        key = _path_key(path)
        if key not in seen_roots:
            seen_roots.add(key)
            candidates.append(provider_path)

    inventory = Inventory()
    seen_skill_roots: set[str] = set()
    for provider_path in candidates:
        root = provider_path.path
        if not root.exists():
            continue
        try:
            skill_roots = _skill_roots(root)
        except OSError as exc:
            inventory.errors.append(f"cannot inspect {root}: {exc}")
            continue
        for skill_root in skill_roots:
            key = _path_key(skill_root)
            if key in seen_skill_roots:
                continue
            seen_skill_roots.add(key)
            try:
                skill = parse_skill(skill_root, provider=provider_path.provider, scope=provider_path.scope)
            except (SkillParseError, OSError) as exc:
                inventory.errors.append(f"cannot parse {skill_root}: {exc}")
                continue
            inventory.installs.append(DiscoveredInstall(skill=skill, provider_path=provider_path))

    _build_groups(inventory)
    inventory.installs.sort(key=lambda item: str(item.root_path).casefold())
    return inventory


def _infer_home(config: AppConfig) -> Path:
    known = [Path(path).expanduser() for path in config.scan_paths]
    for path in known:
        if path.name in {"skills", "rules"} and path.parent.name.startswith("."):
            return path.parent.parent
    return Path.home()


def _ownership_for(
    path: Path,
    defaults: list[ProviderPath],
    known: dict[str, ProviderPath],
    cwd: Path,
) -> ProviderPath:
    direct = known.get(_path_key(path))
    if direct:
        return direct
    resolved = path.expanduser().resolve()
    matches: list[ProviderPath] = []
    for item in defaults:
        try:
            resolved.relative_to(item.path.resolve())
        except ValueError:
            continue
        matches.append(item)
    if matches:
        return max(matches, key=lambda item: len(item.path.parts))
    scope = Scope.PROJECT if _is_relative_to(resolved, cwd) else Scope.CUSTOM
    return ProviderPath(Provider.CUSTOM, resolved, scope)


def _skill_roots(root: Path) -> list[Path]:
    if root.is_file():
        return [root.parent] if root.name == "SKILL.md" else []
    direct = root / "SKILL.md"
    if direct.is_file():
        return [root]
    result: list[Path] = []
    for marker in root.rglob("SKILL.md"):
        if marker.is_symlink() or not marker.is_file() or ".git" in marker.parts:
            continue
        result.append(marker.parent)
    return sorted(result, key=lambda item: item.as_posix().casefold())


def _build_groups(inventory: Inventory) -> None:
    by_hash: dict[str, list[SkillRecord]] = {}
    by_name: dict[str, list[SkillRecord]] = {}
    for skill in inventory.unique_skills:
        by_hash.setdefault(_implementation_hash(skill), []).append(skill)
        by_name.setdefault(skill.name.casefold(), []).append(skill)
    inventory.hash_duplicate_groups = [
        sorted(group, key=lambda skill: skill.skill_id)
        for group in by_hash.values()
        if len(group) > 1
    ]
    inventory.hash_duplicate_groups.sort(key=lambda group: [skill.skill_id for skill in group])
    inventory.name_groups = {
        name: sorted(group, key=lambda skill: skill.skill_id)
        for name, group in by_name.items()
        if len(group) > 1
    }


def _implementation_hash(skill: SkillRecord) -> str:
    fields = [
        skill.body.strip(),
        "|".join(sorted(value.casefold() for value in skill.tools)),
        "|".join(sorted(value.casefold() for value in skill.permissions)),
        "|".join(sorted(value.casefold() for value in skill.environments)),
        "|".join(sorted(value.casefold() for value in skill.inputs)),
        "|".join(sorted(value.casefold() for value in skill.outputs)),
    ]
    return hashlib.sha256("\n".join(fields).encode("utf-8")).hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.expanduser().resolve()))
    except OSError:
        return os.path.normcase(str(path.expanduser().absolute()))
