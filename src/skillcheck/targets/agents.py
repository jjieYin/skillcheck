"""Agent ordering and executable discovery helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

from skillcheck.targets.base import AgentId


AGENT_ORDER: tuple[AgentId, ...] = (
    AgentId.CODEX,
    AgentId.CLAUDE,
    AgentId.CURSOR,
    AgentId.AGENTS,
)


def normalize_agent(value: AgentId | str) -> AgentId:
    try:
        return value if isinstance(value, AgentId) else AgentId(value.casefold())
    except (AttributeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in AGENT_ORDER)
        raise ValueError(f"unknown Agent '{value}'; expected one of: {allowed}") from exc


def resolve_executable(
    name: str,
    *,
    search_path: Iterable[Path] | None = None,
    windows: bool | None = None,
) -> Path | None:
    """Resolve an Agent CLI with deterministic Windows suffix precedence.

    ``shutil.which`` is used for the real process PATH.  Tests and callers may
    pass explicit directories through ``search_path`` to avoid changing the
    process environment.  PowerShell scripts are deliberately considered last
    on Windows because ``.cmd``/``.exe`` are non-interactive entry points.
    """

    is_windows = os.name == "nt" if windows is None else windows
    suffixes = (".cmd", ".exe", ".bat", ".ps1", "") if is_windows else ("",)
    directories = [Path(item) for item in search_path] if search_path is not None else None
    if directories is not None:
        for directory in directories:
            for suffix in suffixes:
                candidate = directory / f"{name}{suffix}"
                if candidate.is_file():
                    return candidate.resolve()
        return None
    for suffix in suffixes:
        resolved = shutil.which(f"{name}{suffix}")
        if resolved:
            return Path(resolved).resolve()
    return None


class EmptyTarget:
    """Safe default target used before concrete adapters are registered."""

    def __init__(self, agent: AgentId) -> None:
        self.agent = agent

    def detect(self):
        from skillcheck.targets.base import DetectionResult

        return DetectionResult(agent=self.agent)

