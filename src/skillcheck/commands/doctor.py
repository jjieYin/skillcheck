"""CLI for read-only diagnostics and confirmed repairs."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

from skillcheck.config import app_home
from skillcheck.config.models import AppConfig
from skillcheck.lifecycle.doctor import Doctor


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"(?i)(token|api[_ -]?key|secret|password)", "[redacted]", value)


def _safe_report(report):
    return report.model_copy(
        update={
            "checks": [
                check.model_copy(
                    update={
                        "message": _safe_text(check.message) or "",
                        "remediation": _safe_text(check.remediation),
                    }
                )
                for check in report.checks
            ]
        }
    )


def build_doctor_context(config_path: Path | None):
    path = config_path.expanduser() if config_path else app_home() / "config.yaml"
    config = None
    if path.exists():
        try:
            import yaml

            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            config = AppConfig.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - diagnostics must report malformed configs
            return SimpleNamespace(
                config_path=path,
                config_error=str(type(exc).__name__),
                index_path=app_home() / "index.db",
                reports_path=app_home() / "reports",
                targets_detected=False,
                reviewer_available=False,
            )
    if config is None:
        config = AppConfig.default()
    return SimpleNamespace(
        config_path=path,
        index_path=config.catalog.database_path,
        reports_path=config.reports.directory,
        targets_detected=False,
        reviewer_available=False,
    )


def register(app: typer.Typer) -> None:
    @app.command("doctor")
    def doctor(
        fix: Annotated[bool, typer.Option("--fix", help="生成并预览受控修复计划")] = False,
        yes: Annotated[bool, typer.Option("--yes", help="确认执行修复计划")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        context = build_doctor_context(config)
        service = Doctor(context)
        report = service.run(fix=False)
        public_report = _safe_report(report)
        if as_json:
            typer.echo(public_report.model_dump_json(indent=2))
        else:
            for check in public_report.checks:
                typer.echo(f"[{check.status.value.upper()}] {check.code}: {check.message}")
                if check.remediation:
                    typer.echo(f"  建议：{check.remediation}")
        if fix:
            plan = service.plan(report)
            if plan.actions:
                if not as_json:
                    typer.echo(f"可执行修复：{', '.join(plan.actions)}")
                confirmed = yes or (typer.confirm("确认执行以上修复？") if not as_json else False)
                if confirmed:
                    service.apply(plan)
                    if not as_json:
                        typer.echo("修复已执行，请重新运行 doctor 验证。")
                elif not as_json:
                    typer.echo("未确认，未执行修复。")
        raise typer.Exit(code=report.exit_code)
