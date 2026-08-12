"""Inspect and manage monitor-only cross-Agent Skill sync groups."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config
from skillcheck.governance.analyzer import GovernanceAnalyzer
from skillcheck.governance.repository import GovernanceRepository
from skillcheck.governance.sync_groups import SyncGroupService

groups_app = typer.Typer(
    help="Inspect cross-Agent mirrors and monitor-only sync groups.",
    invoke_without_command=True,
)


def _services(config_path: Path | None):
    config = load_config(config_path, create=False)
    if not config.catalog.initialized:
        raise ValueError("请先运行 skillcheck init")
    database = CatalogDatabase(config.catalog.database_path)
    database.initialize()
    catalog = CatalogRepository(database)
    return catalog, GovernanceRepository(catalog), SyncGroupService(catalog), GovernanceAnalyzer(catalog)


def _emit(value: object, as_json: bool) -> None:
    if as_json:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        elif isinstance(value, list):
            value = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def _render_group(group) -> str:
    members = ", ".join(f"{item.skill_id} ({item.role.value})" for item in group.members)
    return f"{group.group_id}\t{group.status.value}\t{group.name}\t{members}"


@groups_app.callback()
def groups_callback(ctx: typer.Context) -> None:
    """Show a concise list when no groups subcommand is supplied."""
    if ctx.invoked_subcommand is None:
        list_groups()


@groups_app.command("list")
def list_groups(
    as_json: Annotated[bool, typer.Option("--json")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """List sync groups and refresh their derived status."""
    try:
        _, _, service, _ = _services(config)
        groups = service.list()
        if as_json:
            _emit(groups, True)
            return
        if not groups:
            typer.echo("暂无同步组")
            return
        for group in groups:
            typer.echo(_render_group(group))
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@groups_app.command("show")
def show_group(
    group_id: Annotated[str, typer.Argument()],
    as_json: Annotated[bool, typer.Option("--json")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Show one sync group and its baseline members."""
    try:
        _, _, service, _ = _services(config)
        group = service.get(group_id)
        if group is None:
            raise ValueError(f"unknown sync group: {group_id}")
        if as_json:
            _emit(group, True)
            return
        typer.echo(_render_group(group))
        typer.echo(f"基线 revision: {group.baseline_revision}")
        typer.echo(f"策略: {group.policy.value}（只监测，不自动覆盖）")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@groups_app.command("remove")
def remove_group(
    group_id: Annotated[str, typer.Argument()],
    yes: Annotated[bool, typer.Option("--yes")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Remove only sync-group metadata; never remove Skill files."""
    try:
        _, _, service, _ = _services(config)
        if service.get(group_id) is None:
            raise ValueError(f"unknown sync group: {group_id}")
        confirmed = yes or typer.confirm("确认删除同步组元数据？（不会删除任何 Skill 文件）")
        if not confirmed:
            typer.echo("已取消，未修改任何文件。")
            return
        service.remove(group_id)
        typer.echo(f"已删除同步组元数据：{group_id}")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@groups_app.command("create")
def create_group(
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    candidate: Annotated[str | None, typer.Option("--candidate")] = None,
    authority: Annotated[str | None, typer.Option("--authority")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    yes: Annotated[bool, typer.Option("--yes")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Create a monitor-only group from a MIRRORED_COPY analysis candidate."""
    try:
        _, governance, service, analyzer = _services(config)
        analysis = None
        if not run_id:
            analysis = analyzer.analyze_library(limit=None, trigger_source="cli")
            run_id = analysis.run_id
        context = governance.review_context(run_id)
        options = [item for item in context.groups if item.relation == "MIRRORED_COPY"]
        if not options:
            raise ValueError("analysis run has no MIRRORED_COPY candidate")
        if not candidate:
            if not typer.confirm("使用第一个 MIRRORED_COPY 候选？"):
                typer.echo("已取消，未创建同步组。")
                return
            candidate = options[0].group_id
        selected = next((item for item in options if item.group_id == candidate), None)
        if selected is None:
            raise ValueError(f"candidate is not a MIRRORED_COPY group: {candidate}")
        if not authority:
            authority = selected.member_skill_ids[0]
        if authority not in selected.member_skill_ids:
            raise ValueError("authority must belong to the candidate group")
        group_name = name or f"mirror-{candidate}"
        if not yes and not typer.confirm(
            f"确认创建只监测同步组 {group_name}？（不会复制或修改 Skill 文件）"
        ):
            typer.echo("已取消，未创建同步组。")
            return
        members = [skill_id for skill_id in selected.member_skill_ids if skill_id != authority]
        saved = service.create_from_analysis(
            run_id=run_id,
            group_id=candidate,
            name=group_name,
            authority_skill_id=authority,
            member_skill_ids=members,
        )
        _emit(saved, True)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc


def register(app: typer.Typer) -> None:
    app.add_typer(groups_app, name="groups")
