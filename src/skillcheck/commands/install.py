"""Configure local Codex, Claude Code and Cursor integrations."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

import typer

from skillcheck.config import load_config, load_or_create_config
from skillcheck.pipelines.install_pipeline import InstallPipeline
from skillcheck.targets.base import AgentId, AgentTarget
from skillcheck.targets.claude import ClaudeTarget
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.cursor import CursorTarget
from skillcheck.targets.registry import TargetRegistry

SUPPORTED_TARGETS = ("codex", "claude", "cursor")


def _build_install_pipeline(loaded) -> InstallPipeline:
    home = Path.home()
    project = Path.cwd()
    skill_paths = loaded.scan_paths + loaded.extra_paths
    targets: dict[AgentId, AgentTarget] = {
        AgentId.CODEX: CodexTarget(
            global_config=home / ".codex" / "config.toml",
            project_config=project / ".codex" / "config.toml",
            skill_paths=skill_paths,
        ),
        AgentId.CLAUDE: ClaudeTarget(
            global_config=home / ".claude.json",
            project_config=project / ".claude" / "settings.json",
            skill_paths=skill_paths,
        ),
        AgentId.CURSOR: CursorTarget(
            global_config=home / ".cursor" / "mcp.json",
            project_config=project / ".cursor" / "mcp.json",
            skill_paths=skill_paths,
        ),
    }
    return InstallPipeline(TargetRegistry(targets))


def build_install_pipeline(config_path: Path | None = None, *, create: bool = True) -> InstallPipeline:
    loaded = (
        load_or_create_config(config_path)
        if create
        else load_config(config_path, create=False)
    )
    return _build_install_pipeline(loaded)


def _selected_targets(pipeline: InstallPipeline, requested: str) -> list[str]:
    normalized = requested.strip().casefold()
    if normalized == "all":
        return list(SUPPORTED_TARGETS)
    if normalized == "auto":
        return [
            item.agent.value
            for item in pipeline.discover().agents
            if item.agent.value in SUPPORTED_TARGETS
            and (item.cli_path is not None or item.config_path is not None or item.instructions_configured)
        ]
    selected = [part.strip().casefold() for part in requested.split(",") if part.strip()]
    if not selected or any(item not in SUPPORTED_TARGETS for item in selected):
        allowed = "auto, all, " + ", ".join(SUPPORTED_TARGETS)
        raise ValueError(f"--target must be one of: {allowed}")
    return list(dict.fromkeys(selected))


def register(app: typer.Typer) -> None:
    @app.command("install")
    def install(
        target: Annotated[str, typer.Option("--target")] = "auto",
        location: Annotated[
            Literal["global", "project"], typer.Option("--location")
        ] = "global",
        yes: Annotated[bool, typer.Option("--yes", help="Apply without a confirmation prompt")] = False,
        print_config: Annotated[
            str | None,
            typer.Option("--print-config", metavar="TARGET", help="Print MCP config without writing files"),
        ] = None,
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        try:
            pipeline = build_install_pipeline(config, create=print_config is None)
            if print_config is not None:
                selected = _selected_targets(pipeline, print_config)
                if len(selected) != 1:
                    raise ValueError("--print-config requires exactly one target")
                change = pipeline.registry.get(selected[0]).preview(location)
                typer.echo(change.after_text, nl=False)
                return

            selected = _selected_targets(pipeline, target)
            if target.casefold() == "auto" and selected and sys.stdin.isatty():
                detected = ",".join(selected)
                choice = typer.prompt(
                    "Select Agent targets (comma separated)",
                    default=detected,
                )
                selected = _selected_targets(pipeline, choice)
            if not selected:
                typer.echo("No installed Agent was detected. Use --target all to configure all supported Agents.")
                return
            preview = pipeline.preview(selected, scope=location)
            for change in preview.changes:
                typer.echo(f"- {change.kind}: {change.path}")
            confirmed = yes or (sys.stdin.isatty() and typer.confirm("Apply these Skillcheck changes?"))
            if not confirmed:
                pipeline.apply(preview, confirmed=False)
                typer.echo("Cancelled; no files were changed.")
                return
            result = pipeline.apply(preview, confirmed=True)
            typer.echo(f"Configured {len(result.changed_files)} file(s).")
            for validation in result.validations:
                typer.echo(f"- {validation}")
        except typer.Exit:
            raise
        except (KeyError, ValueError, RuntimeError, OSError) as exc:
            typer.echo(f"install failed: {exc}", err=True)
            raise typer.Exit(code=2) from exc
