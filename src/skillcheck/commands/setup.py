"""Interactive Agent detection and configuration setup command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

import typer

from skillcheck.config import app_home, load_or_create_config, save_config
from skillcheck.config.models import AppConfig
from skillcheck.pipelines.setup_pipeline import SetupPipeline
from skillcheck.targets.agents import EmptyTarget
from skillcheck.targets.base import AgentId
from skillcheck.targets.claude import ClaudeTarget
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.cursor import CursorTarget
from skillcheck.targets.registry import TargetRegistry


class FileTargetConfigStore:
    def __init__(self, path: Path, config: AppConfig) -> None:
        self.path = path
        self.config = config

    def record_targets(self, scope: str, results, validations) -> None:
        self.config.targets.configured = [
            result.agent.value for result in results if getattr(result, "agent", None) is not None
        ]
        self.config.targets.scope = scope
        self.config.targets.last_validated = bool(validations) and all(validations)
        save_config(self.path, self.config)


def _config_path(path: Path | None) -> Path:
    if path is not None:
        return path.expanduser()
    return app_home() / "config.yaml"


def build_setup_pipeline(config_path: Path | None) -> SetupPipeline:
    loaded = load_or_create_config(config_path)
    home = Path.home()
    project = Path.cwd()
    registry = TargetRegistry(
        {
            AgentId.CODEX: CodexTarget(
                global_config=home / ".codex" / "config.toml",
                project_config=project / ".codex" / "config.toml",
                skill_paths=loaded.scan_paths + loaded.extra_paths,
            ),
            AgentId.CLAUDE: ClaudeTarget(
                global_config=home / ".claude.json",
                project_config=project / ".claude" / "settings.json",
                skill_paths=loaded.scan_paths + loaded.extra_paths,
            ),
            AgentId.CURSOR: CursorTarget(
                global_config=home / ".cursor" / "mcp.json",
                project_config=project / ".cursor" / "mcp.json",
                skill_paths=loaded.scan_paths + loaded.extra_paths,
            ),
            AgentId.AGENTS: EmptyTarget(AgentId.AGENTS),
        }
    )
    return SetupPipeline(registry, FileTargetConfigStore(_config_path(config_path), loaded))


def register(app: typer.Typer) -> None:
    @app.command("setup")
    def setup(
        agents: Annotated[list[str] | None, typer.Option("--agent", "-a")] = None,
        scope: Annotated[Literal["global", "project"], typer.Option("--scope")] = "global",
        yes: Annotated[bool, typer.Option("--yes", help="跳过最终确认")] = False,
        no_interactive: Annotated[bool, typer.Option("--no-interactive")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        try:
            pipeline = build_setup_pipeline(config)
            discovery = pipeline.discover()
            detected = ", ".join(item.agent.value for item in discovery.detections if item.cli_path or item.config_path)
            typer.echo(f"检测到的 Agent：{detected or '未检测到已安装 Agent'}")
            selected = agents or discovery.preselected
            if not selected:
                typer.echo("没有可配置的 Agent，未修改任何配置。")
                return
            typer.echo(f"将配置：{', '.join(selected)}（范围：{scope}）")
            preview = pipeline.preview(selected, scope=scope)
            for change in preview.changes:
                status = "无需修改" if not change.changed else "将写入"
                typer.echo(f"- {change.path}：{status}")
                for summary in change.summary:
                    typer.echo(f"  {summary}")
            confirmed = yes
            if not confirmed and not no_interactive and sys.stdin.isatty():
                confirmed = typer.confirm("确认写入以上配置？")
            if not confirmed:
                result = pipeline.apply(preview, confirmed=False)
                typer.echo("已取消，未修改任何配置。")
                return
            result = pipeline.apply(preview, confirmed=True)
            if not all(result.validations):
                typer.echo("配置已写入，但验证未全部通过。", err=True)
                raise typer.Exit(code=2)
            if result.changed_files:
                typer.echo(f"配置完成：修改 {len(result.changed_files)} 个文件。")
            else:
                typer.echo("配置已是最新，无需修改。")
        except typer.Exit:
            raise
        except (KeyError, ValueError) as exc:
            typer.echo(f"setup 失败：{exc}", err=True)
            raise typer.Exit(code=2) from exc
        except Exception as exc:
            typer.echo(f"setup 失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc
