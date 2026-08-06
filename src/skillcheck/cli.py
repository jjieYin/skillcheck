from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from skillcheck import __version__
from skillcheck.config import load_or_create_config
from skillcheck.llm import LLMReviewer, OpenAICompatibleClient
from skillcheck.models import Decision
from skillcheck.reports import ReportWriter
from skillcheck.service import build_service

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Manage a personal local Skill inventory."""


@app.command()
def version() -> None:
    """Print the installed skillcheck version."""
    typer.echo(f"skillcheck {__version__}")


@app.command()
def init(
    config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    home: Path | None = typer.Option(None, "--home", help="用于生成默认扫描目录的用户目录"),
) -> None:
    """Create a secret-free local configuration and state directories."""
    try:
        loaded = load_or_create_config(config, home=home)
        loaded.index_path.parent.mkdir(parents=True, exist_ok=True)
        loaded.reports_path.mkdir(parents=True, exist_ok=True)
        loaded.staging_path.mkdir(parents=True, exist_ok=True)
        typer.echo(f"已初始化 skillcheck 配置：{config or loaded.index_path.parent / 'config.yaml'}")
    except Exception as exc:
        typer.echo(f"初始化失败：{exc}", err=True)
        raise typer.Exit(code=3) from exc


@app.command()
def scan(
    config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    cwd: Path | None = typer.Option(None, "--cwd", help="项目目录"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """Discover local Skills and refresh the SQLite index."""
    try:
        service = _service_from_config(config)
        result = service.scan(cwd=cwd)
        payload = {
            "installation_count": result.installation_count,
            "unique_skill_count": result.unique_skill_count,
            "hash_duplicate_groups": [
                [skill.skill_id for skill in group] for group in result.inventory.hash_duplicate_groups
            ],
            "errors": result.inventory.errors,
        }
        if as_json:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            typer.echo(f"已扫描 {result.installation_count} 个 Skill，索引中有 {result.unique_skill_count} 个。")
            if result.inventory.hash_duplicate_groups:
                typer.echo(f"发现 {len(result.inventory.hash_duplicate_groups)} 组内容重复。")
            for error in result.inventory.errors:
                typer.echo(f"警告：{error}")
    except Exception as exc:
        typer.echo(f"扫描失败：{exc}", err=True)
        raise typer.Exit(code=3) from exc


@app.command(name="list")
def list_command(
    duplicates: bool = typer.Option(False, "--duplicates", help="只显示重复内容组"),
    provider: str | None = typer.Option(None, "--provider", help="按 provider 过滤"),
    config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """List indexed Skills."""
    try:
        service = _service_from_config(config)
        skills = service.list_skills(provider=provider, duplicates=duplicates)
        payload = [skill.model_dump(mode="json") for skill in skills]
        if as_json:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for skill in skills:
                typer.echo(f"{skill.skill_id}\t{skill.name}\t{skill.provider or 'custom'}\t{skill.root_path}")
            if not skills:
                typer.echo("索引中没有匹配的 Skill。")
    except Exception as exc:
        typer.echo(f"读取索引失败：{exc}", err=True)
        raise typer.Exit(code=3) from exc


@app.command()
def audit(
    path: Path | None = typer.Option(None, "--path", help="只审计指定目录下的 Skill"),
    provider: str | None = typer.Option(None, "--provider", help="只审计指定 provider"),
    no_llm: bool = typer.Option(False, "--no-llm", help="禁用 LLM 复核"),
    refresh: bool = typer.Option(False, "--refresh", help="先重新扫描再审计"),
    config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """Audit the existing local Skill library without installing anything."""
    try:
        service = _service_from_config(config)
        result = service.audit(path=path, provider=provider, use_llm=not no_llm, refresh=refresh)
        if as_json:
            typer.echo(result.paths.json.read_text(encoding="utf-8"))
        else:
            typer.echo(f"审计报告：{result.paths.markdown}")
            typer.echo(f"扫描 {result.report.installation_count} 个实例，发现 {len(result.report.groups)} 个治理分组。")
        raise typer.Exit(code=_audit_exit_code(result.report.groups))
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"审计失败：{exc}", err=True)
        raise typer.Exit(code=3) from exc


@app.command()
def check(
    source: str = typer.Argument(..., help="目录、ZIP 或 HTTPS GitHub URL"),
    top_k: int = typer.Option(5, "--top-k", min=1, max=100, help="返回候选数量"),
    no_llm: bool = typer.Option(False, "--no-llm", help="禁用 LLM 复核"),
    strict: bool = typer.Option(False, "--strict", help="任何非通过结果都返回 2"),
    config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """Check a new Skill source before installation."""
    try:
        service = _service_from_config(config)
        result = service.check(source, use_llm=not no_llm, top_k=top_k)
        if as_json:
            typer.echo(result.paths.json.read_text(encoding="utf-8"))
        else:
            typer.echo(f"检查报告：{result.paths.markdown}")
            typer.echo(f"决策：{result.report.decision.value}（置信度：{result.report.confidence}）")
        raise typer.Exit(code=_decision_exit_code(result.report.decision, strict=strict))
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"检查失败：{exc}", err=True)
        raise typer.Exit(code=3) from exc


@app.command()
def report(
    action: str = typer.Argument(..., help="latest、show 或 open"),
    report_id: str | None = typer.Argument(None, help="show/open 使用的报告 ID"),
    config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """View the latest or a specific report."""
    try:
        loaded = load_or_create_config(config)
        writer = ReportWriter(loaded.reports_path)
        if action == "latest":
            paths = writer.latest()
            if paths is None:
                raise FileNotFoundError("没有报告")
        elif action in {"show", "open"} and report_id:
            paths = writer.find(report_id)
        else:
            raise ValueError("用法：skillcheck report latest|show REPORT_ID|open REPORT_ID")
        if action == "open":
            _open_report(paths.markdown)
        elif as_json:
            typer.echo(paths.json.read_text(encoding="utf-8"))
        else:
            typer.echo(paths.markdown.read_text(encoding="utf-8"))
    except Exception as exc:
        typer.echo(f"读取报告失败：{exc}", err=True)
        raise typer.Exit(code=3) from exc


def _service_from_config(config_path: Path | None):
    config = load_or_create_config(config_path)
    reviewer = None
    if config.llm.enabled and config.llm.api_key:
        reviewer = LLMReviewer(
            OpenAICompatibleClient(
                api_key=config.llm.api_key,
                model=config.llm.model,
                base_url=config.llm.base_url,
            )
        )
    return build_service(config, reviewer=reviewer)


def _decision_exit_code(decision: Decision, *, strict: bool = False) -> int:
    if strict and decision not in {Decision.PASS, Decision.APPROVE}:
        return 2
    if decision in {Decision.PASS, Decision.APPROVE}:
        return 0
    if decision in {Decision.MODIFY, Decision.VARIANT, Decision.SIMILAR, Decision.MANUAL_REVIEW}:
        return 1
    return 2


def _audit_exit_code(groups: list) -> int:
    if not groups:
        return 0
    if any(group.relation in {"EXACT_DUPLICATE", "CONFLICT_GROUP", "QUALITY_ISSUE"} for group in groups):
        return 2
    return 1


def _open_report(path: Path) -> None:
    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        startfile(str(path))
    else:
        typer.echo(str(path))
