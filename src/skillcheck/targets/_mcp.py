"""Shared implementation for JSON and TOML MCP target adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal

from skillcheck.targets.agents import resolve_executable
from skillcheck.targets.base import AgentId, ConfigChange, DetectionResult
from skillcheck.targets.config_io import (
    ConfigFormatError,
    ConfigWriteResult,
    atomic_replace,
    content_hash,
    load_document,
    mcp_entry_matches,
    read_mcp_entry,
    render_document,
    write_mcp_entry,
)


class McpTarget:
    """Base adapter that edits exactly one ``skillcheck`` MCP entry."""

    format: Literal["json", "toml"]
    container_name: str

    def __init__(
        self,
        config_path: Path | str | None = None,
        *,
        global_config: Path | str | None = None,
        project_config: Path | str | None = None,
        launcher: str = "skillcheck",
        cli_search_path: Iterable[Path] | None = None,
        skill_paths: Iterable[Path] | None = None,
    ) -> None:
        if config_path is not None and global_config is None:
            global_config = config_path
        self.global_config = Path(global_config).expanduser() if global_config else None
        self.project_config = Path(project_config).expanduser() if project_config else None
        self.launcher = launcher
        self.cli_search_path = list(cli_search_path) if cli_search_path is not None else None
        self._skill_paths = [Path(item).expanduser() for item in skill_paths or ()]

    def _path_for(self, scope: str) -> Path:
        normalized = scope.casefold()
        if normalized == "global":
            if self.global_config is None:
                raise ValueError(f"{self.agent.value} 未配置全局配置路径")
            return self.global_config
        if normalized == "project":
            if self.project_config is None:
                raise ValueError(f"{self.agent.value} 未配置项目配置路径")
            return self.project_config
        raise ValueError("scope 必须是 global 或 project")

    @property
    def config_path(self) -> Path | None:
        """Compatibility alias used by setup discovery."""

        return self.global_config

    def _entry(self) -> dict[str, object]:
        return {"command": self.launcher, "args": ["serve", "--mcp"]}

    def detect(self) -> DetectionResult:
        existing = next(
            (path for path in (self.global_config, self.project_config) if path is not None and path.exists()),
            None,
        )
        return DetectionResult(
            agent=self.agent,
            cli_path=resolve_executable(
                self.agent.value,
                search_path=self.cli_search_path,
            ),
            config_path=existing,
            skill_paths=[path for path in self._skill_paths if path.exists()],
            mcp_configured=self._has_entry(existing) if existing else False,
            supports_global=self.global_config is not None,
            supports_project=self.project_config is not None,
        )

    def _has_entry(self, path: Path) -> bool:
        document, _, _ = load_document(path, self.format)
        return read_mcp_entry(document, self.format, "skillcheck") is not None

    def preview(self, scope: str) -> ConfigChange:
        path = self._path_for(scope)
        document, text, before_hash = load_document(path, self.format)
        entry = self._entry()
        existing = read_mcp_entry(document, self.format, "skillcheck")
        changed = not mcp_entry_matches(existing, entry)
        if changed:
            write_mcp_entry(document, self.format, "skillcheck", entry)
            after_text = render_document(document, self.format)
            summary = [f"写入 {self.agent.value} 的 skillcheck MCP 配置"]
        else:
            after_text = text
            summary = ["skillcheck MCP 配置已存在，无需修改"]
        return ConfigChange(
            agent=self.agent,
            path=path,
            before_hash=before_hash,
            after_text=after_text,
            summary=summary,
            changed=changed,
        )

    def install(self, change: ConfigChange) -> ConfigWriteResult:
        if change.agent != self.agent:
            raise ValueError(f"配置变更属于 {change.agent.value}，不能由 {self.agent.value} 执行")
        if change.changed:
            atomic_replace(change.path, change.after_text, expected_hash=change.before_hash)
        return ConfigWriteResult(
            path=change.path,
            changed=change.changed,
            summary=tuple(change.summary),
        )

    def uninstall(self, scope: str) -> ConfigWriteResult:
        path = self._path_for(scope)
        if not path.exists():
            return ConfigWriteResult(path=path, changed=False, summary=("配置不存在，无需卸载",))
        document, text, before_hash = load_document(path, self.format)
        if read_mcp_entry(document, self.format, "skillcheck") is None:
            return ConfigWriteResult(path=path, changed=False, summary=("skillcheck MCP 配置不存在",))
        write_mcp_entry(document, self.format, "skillcheck", None)
        after_text = render_document(document, self.format)
        atomic_replace(path, after_text, expected_hash=before_hash)
        return ConfigWriteResult(
            path=path,
            changed=True,
            summary=(f"移除 {self.agent.value} 的 skillcheck MCP 配置",),
        )

    def validate(self, scope: str) -> bool:
        path = self._path_for(scope)
        if not path.exists():
            return False
        document, _, _ = load_document(path, self.format)
        return mcp_entry_matches(read_mcp_entry(document, self.format, "skillcheck"), self._entry())
