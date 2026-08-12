"""Read-only status for the local Skillcheck catalog and Agent integration."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from pydantic import BaseModel, Field

from skillcheck.catalog.database import CatalogDatabase, IncompatibleCatalogError
from skillcheck.catalog.repository import CatalogRepository
from skillcheck.config import load_config


class SkillcheckStatus(BaseModel):
    configured_agents: list[str] = Field(default_factory=list)
    selection_initialized: bool = False
    initialized: bool
    root_count: int = 0
    skill_count: int = 0
    revision: str | None = None
    last_sync: datetime | None = None
    watch_mode: str = "on_mcp_connection"
    pending_count: int = 0
    warnings: list[str] = Field(default_factory=list)


def read_status(config_path: Path | str | None = None) -> SkillcheckStatus:
    """Return state without creating or changing a catalog."""

    config = load_config(config_path)
    result = SkillcheckStatus(
        configured_agents=list(config.targets.configured),
        selection_initialized=config.targets.selection_initialized,
        initialized=config.catalog.initialized,
    )
    if not config.catalog.initialized:
        return result
    if not config.catalog.database_path.is_file():
        return result.model_copy(update={"warnings": ["catalog database is missing; run skillcheck init"]})

    try:
        database = CatalogDatabase(config.catalog.database_path)
        database.initialize()
        repository = CatalogRepository(database)
        with database.connect() as connection:
            latest = connection.execute(
                """SELECT revision, completed_at FROM sync_events
                   ORDER BY completed_at DESC, event_id DESC LIMIT 1"""
            ).fetchone()
        return result.model_copy(
            update={
                "root_count": len(repository.list_roots()),
                "skill_count": len(repository.list_current_skills()),
                "revision": latest["revision"] if latest else None,
                "last_sync": datetime.fromisoformat(latest["completed_at"]) if latest else None,
            }
        )
    except IncompatibleCatalogError as error:
        return result.model_copy(update={"warnings": [str(error)]})


def render_status(status: SkillcheckStatus) -> str:
    agents = ", ".join(status.configured_agents) if status.configured_agents else "未配置"
    lines = [
        f"已接入 Agent：{agents}",
        f"Agent 选择：{'已保存' if status.selection_initialized else '待确认'}",
        f"Skills 索引：{'已初始化' if status.initialized else '未初始化'}",
        f"索引目录：{status.root_count}，Skill：{status.skill_count}",
        f"监听模式：{status.watch_mode}",
    ]
    if status.revision:
        lines.append(f"最近同步：{status.last_sync}（{status.revision}）")
    lines.extend(f"提示：{warning}" for warning in status.warnings)
    lines.append("请在 Agent 中直接提出 Skills 检查需求。")
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    @app.command("status")
    def status(
        config: Path | None = typer.Option(None, "--config"),
        as_json: bool = typer.Option(False, "--json"),
    ) -> None:
        snapshot = read_status(config)
        if as_json:
            typer.echo(json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return
        typer.echo(render_status(snapshot))
