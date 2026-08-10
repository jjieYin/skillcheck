from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from skillcheck.config import load_or_create_config
from skillcheck.models import Decision
from skillcheck.pipelines.add_pipeline import AddPipeline, AddRequest
from skillcheck.pipelines.scan_pipeline import ReviewMode


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


def register(app: typer.Typer) -> None:
    @app.command("add")
    def add(
        source: Annotated[str, typer.Argument(help="目录、ZIP 或 GitHub URL")],
        target: Annotated[list[str], typer.Option("--target", "-t")] = [],
        review: Annotated[ReviewMode, typer.Option("--review")] = ReviewMode.NONE,
        check_only: Annotated[bool, typer.Option("--check-only")] = False,
        yes: Annotated[bool, typer.Option("--yes")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        pipeline = build_add_pipeline(config)
        configuration = getattr(pipeline, "config", None)
        if configuration is None:
            configuration = load_or_create_config(config)
        targets = target or ["codex"]
        request = AddRequest(
            source=source,
            targets=targets,
            target_paths=[_target_root(item, configuration) for item in targets],
            review=review.value,
            confirmed=False,
        )
        prepared = pipeline.prepare(request)
        typer.echo(f"检查结论：{prepared.report.decision.value}")
        typer.echo(f"来源哈希：{prepared.report.source_hash}")
        if getattr(prepared, "paths", None) is not None:
            typer.echo(f"报告：{prepared.paths.markdown}")
        if check_only:
            return
        if prepared.report.decision not in {Decision.PASS, Decision.APPROVE, Decision.VARIANT, Decision.MODIFY}:
            raise typer.BadParameter(f"当前结论不能直接安装：{prepared.report.decision.value}")
        confirmed = yes or typer.confirm(f"确认安装到 {', '.join(str(path) for path in request.target_paths)}？")
        if not confirmed:
            typer.echo("已保留报告，未安装。")
            return
        installed = pipeline.execute(prepared)
        for path in installed:
            typer.echo(f"已安装：{path}")
