"""Compatibility commands for the v0.1 command surface.

The v0.2 application has a smaller public vocabulary (``scan`` and ``add``),
but scripts written against v0.1 should continue to work for one release
cycle.  The shims deliberately reuse the existing service and report formats
instead of silently changing the meaning of a command.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from skillcheck.app.context import build_add_pipeline, build_scan_pipeline
from skillcheck.config import load_or_create_config
from skillcheck.installer import InstallBlocked, Installer
from skillcheck.models import CheckReport, Decision
from skillcheck.pipelines.add_pipeline import AddRequest
from skillcheck.pipelines.scan_pipeline import ReviewMode, ScanScope
from skillcheck.reports import ReportWriter
from skillcheck.service import build_service


def _initialise(config_path: Path | None, home: Path | None) -> Path:
    loaded = load_or_create_config(config_path, home=home)
    loaded.index_path.parent.mkdir(parents=True, exist_ok=True)
    loaded.reports_path.mkdir(parents=True, exist_ok=True)
    loaded.staging_path.mkdir(parents=True, exist_ok=True)
    return config_path or loaded.index_path.parent / "config.yaml"


def _path_value(value) -> Path:
    return Path(value).expanduser() if value else Path.cwd()


def _json_from_report(report_paths) -> str:
    path = getattr(report_paths, "json_path", None) or getattr(report_paths, "json", None)
    return Path(path).read_text(encoding="utf-8")


def _scan_exit_code(payload: dict) -> int:
    groups = payload.get("groups", [])
    if any(
        group.get("relation") in {"EXACT_DUPLICATE", "CONFLICT_GROUP", "QUALITY_ISSUE"}
        for group in groups
        if isinstance(group, dict)
    ):
        return 2
    return 1 if groups else 0


def _run_scan(
    *,
    config: Path | None,
    path: Path | None,
    as_json: bool,
    notice: bool = True,
) -> int:
    if notice and not as_json:
        typer.echo("audit 已合并到 scan；正在继续执行 scan。")
    pipeline = build_scan_pipeline(config)
    outcome = pipeline.run(
        ScanScope(paths=[str(path)] if path else []),
        ReviewMode.NONE,
    )
    if as_json:
        text = _json_from_report(outcome.report)
        typer.echo(text, nl=False)
        try:
            return _scan_exit_code(json.loads(text))
        except json.JSONDecodeError:
            return 0
    typer.echo(f"扫描完成：{outcome.skill_count} 个 Skill")
    typer.echo(f"报告：{outcome.report.markdown}")
    return 0


def register(app: typer.Typer) -> None:
    @app.command("setup")
    def setup(
        config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
        home: Path | None = typer.Option(None, "--home", help="用于生成默认扫描目录的用户目录"),
    ) -> None:
        """Create the local configuration and state directories."""
        try:
            target = _initialise(config, home)
            typer.echo(f"已初始化 skillcheck 配置：{target}")
        except Exception as exc:
            typer.echo(f"初始化失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc

    @app.command("init", hidden=True)
    def init_compat(
        config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
        home: Path | None = typer.Option(None, "--home", help="用于生成默认扫描目录的用户目录"),
    ) -> None:
        """Deprecated alias for ``setup``."""
        try:
            target = _initialise(config, home)
            typer.echo("init 已替换为 setup；正在继续执行 setup。")
            typer.echo(f"已初始化 skillcheck 配置：{target}")
        except Exception as exc:
            typer.echo(f"初始化失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc

    @app.command("audit", hidden=True)
    def audit_compat(
        path: Path | None = typer.Option(None, "--path", help="只审计指定目录下的 Skill"),
        provider: str | None = typer.Option(None, "--provider", help="旧版兼容参数"),
        no_llm: bool = typer.Option(False, "--no-llm", help="禁用 Agent 复核"),
        refresh: bool = typer.Option(False, "--refresh", help="旧版兼容参数"),
        config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
        as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
    ) -> None:
        del provider, refresh, no_llm
        try:
            code = _run_scan(config=config, path=path, as_json=as_json)
            raise typer.Exit(code=code)
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"审计失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc

    @app.command("check", hidden=True)
    def check_compat(
        source: str = typer.Argument(..., help="目录、ZIP 或 HTTPS GitHub URL"),
        top_k: int = typer.Option(5, "--top-k", min=1, max=100, help="返回候选数量"),
        no_llm: bool = typer.Option(False, "--no-llm", help="禁用 Agent 复核"),
        strict: bool = typer.Option(False, "--strict", help="任何非通过结果都返回 2"),
        config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
        as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
    ) -> None:
        try:
            pipeline = build_add_pipeline(config)
            request = AddRequest(
                source=source,
                review="none" if no_llm else "legacy",
                top_k=top_k,
            )
            prepared = pipeline.prepare(request)
            if as_json:
                typer.echo(_json_from_report(prepared.paths), nl=False)
            else:
                typer.echo(f"请改用 skillcheck add {source} --check-only；正在兼容执行。")
                typer.echo(f"检查报告：{prepared.paths.markdown if prepared.paths else '已生成'}")
                typer.echo(
                    f"决策：{prepared.report.decision.value}（置信度：{prepared.report.confidence}）"
                )
            raise typer.Exit(code=_decision_exit_code(prepared.report.decision, strict=strict))
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"检查失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc

    @app.command("list", hidden=True)
    def list_compat(
        duplicates: bool = typer.Option(False, "--duplicates", help="只显示重复内容组"),
        provider: str | None = typer.Option(None, "--provider", help="按 provider 过滤"),
        config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
        as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
    ) -> None:
        try:
            service = build_service(load_or_create_config(config))
            skills = service.list_skills(provider=provider, duplicates=duplicates)
            payload = [skill.model_dump(mode="json") for skill in skills]
            if as_json:
                typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                for skill in skills:
                    typer.echo(
                        f"{skill.skill_id}\t{skill.name}\t{skill.provider or 'custom'}\t{skill.root_path}"
                    )
                if not skills:
                    typer.echo("索引中没有匹配的 Skill。")
        except Exception as exc:
            typer.echo(f"读取索引失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc

    @app.command("install", hidden=True)
    def install_compat(
        report_id: str = typer.Argument(..., help="检查报告 ID"),
        target: str = typer.Option(..., "--target", help="codex、claude、agents 或 cursor"),
        name: str | None = typer.Option(None, "--name", help="显式安装名称"),
        yes: bool = typer.Option(False, "--yes", help="跳过交互确认"),
        config: Path | None = typer.Option(None, "--config", help="配置文件路径"),
    ) -> None:
        try:
            loaded = load_or_create_config(config)
            paths = ReportWriter(loaded.reports_path).find(report_id)
            report = CheckReport.model_validate_json(paths.json.read_text(encoding="utf-8"))
            target_root = _provider_target_root(target, loaded)
            confirmed = yes or typer.confirm(
                f"确认将 {report.source} 安装到 {target_root}？（决策：{report.decision.value}）"
            )
            installed = Installer().install(
                report,
                target_root=target_root,
                confirmed=confirmed,
                name=name,
            )
            typer.echo(f"已安装到：{installed}")
        except InstallBlocked as exc:
            typer.echo(f"安装已阻断：{exc}", err=True)
            raise typer.Exit(code=2) from exc
        except Exception as exc:
            typer.echo(f"安装失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc


def _decision_exit_code(decision: Decision | object, *, strict: bool = False) -> int:
    raw = getattr(decision, "value", decision)
    try:
        normalized = Decision(raw)
    except (TypeError, ValueError):
        normalized = Decision.MANUAL_REVIEW
    if strict and normalized not in {Decision.PASS, Decision.APPROVE}:
        return 2
    if normalized in {Decision.PASS, Decision.APPROVE}:
        return 0
    if normalized in {Decision.MODIFY, Decision.VARIANT, Decision.SIMILAR, Decision.MANUAL_REVIEW}:
        return 1
    return 2


def _provider_target_root(provider: str, config) -> Path:
    normalized = provider.casefold()
    if normalized not in {"codex", "claude", "agents", "cursor"}:
        raise ValueError("target must be codex, claude, agents, or cursor")
    for configured in [*config.scan_paths, *config.extra_paths]:
        parts = {part.casefold() for part in Path(configured).parts}
        if f".{normalized}" in parts:
            return Path(configured).expanduser().resolve()
    home = Path.home()
    leaf = "rules" if normalized == "cursor" else "skills"
    return (home / f".{normalized}" / leaf).resolve()
