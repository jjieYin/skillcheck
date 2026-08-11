from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from skillcheck.config import load_or_create_config


def build_add_pipeline(config: Path | None):
    from skillcheck.app.context import build_add_pipeline as factory

    return factory(config)


def _target_root(provider: str, config) -> Path:
    normalized = provider.casefold()
    if normalized not in {"codex", "claude", "agents", "cursor"}:
        raise typer.BadParameter("target 必须是 codex、claude、agents 或 cursor")
    for configured in [*config.scan_paths, *config.extra_paths]:
        parts = {part.casefold() for part in Path(configured).parts}
        if f".{normalized}" in parts:
            return Path(configured).expanduser().resolve()
    leaf = "rules" if normalized == "cursor" else "skills"
    return (Path.home() / f".{normalized}" / leaf).resolve()


def _render_prepared(prepared) -> None:
    typer.echo(f"来源哈希：{prepared.source_hash}")
    typer.echo(f"Agent 建议状态：{prepared.review_state}")
    typer.echo(f"目标路径：{', '.join(str(path) for path in prepared.target_paths)}")
    typer.echo(f"文件数量：{len(prepared.files)}")
    if prepared.deterministic_blockers:
        rule_ids = ", ".join(item.rule_id for item in prepared.deterministic_blockers)
        typer.echo(f"确定性阻断项：{rule_ids}")
    else:
        typer.echo("确定性阻断项：无")


def register(app: typer.Typer) -> None:
    @app.command("add")
    def add(
        source: Annotated[str, typer.Argument(help="目录、ZIP 或 GitHub URL")],
        target: Annotated[list[str] | None, typer.Option("--target", "-t")] = None,
        yes: Annotated[bool, typer.Option("--yes", help="确认后直接安装")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        try:
            pipeline = build_add_pipeline(config)
            configuration = getattr(pipeline, "config", None) or load_or_create_config(config)
            targets = target or ["codex"]
            target_paths = [_target_root(item, configuration) for item in targets]
            prepared = pipeline.prepare(source, targets, target_paths)
            _render_prepared(prepared)
            if prepared.deterministic_blockers:
                raise typer.BadParameter("来源存在确定性安全阻断项，未安装")
            confirmed = yes or typer.confirm("确认安装到以上目标路径？")
            if not confirmed:
                typer.echo("已保留预检结果，未安装。")
                return
            result = pipeline.execute(prepared, confirmed=True)
            for path in result.installed_paths:
                typer.echo(f"已安装：{path}")
        except typer.Exit:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            typer.echo(f"add failed: {exc}", err=True)
            raise typer.Exit(code=2) from exc
