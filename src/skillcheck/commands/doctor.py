"""CLI for read-only diagnostics and confirmed repairs."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

from skillcheck.catalog.database import CatalogDatabase
from skillcheck.commands.install import _build_install_pipeline
from skillcheck.config import app_home, load_config, save_config
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


def _latest_sync_warning(path: Path) -> str | None:
    """Read the newest catalog warning without creating or modifying a database."""

    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        uri = f"{path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute(
                "SELECT warnings_json FROM sync_events ORDER BY completed_at DESC, event_id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        if isinstance(payload, list):
            warnings = [str(item) for item in payload if str(item).strip()]
            return "; ".join(warnings) or None
        return str(payload).strip() or None
    except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
        return None


def build_doctor_context(config_path: Path | None):
    path = config_path.expanduser() if config_path else app_home() / "config.yaml"
    try:
        config = load_config(path, create=False)
    except Exception as exc:  # noqa: BLE001 - diagnostics must report malformed configs
        return SimpleNamespace(
            config_path=path,
            config_error=str(type(exc).__name__),
            index_path=app_home() / "index.db",
            reports_path=app_home() / "reports",
            targets_detected=False,
            reviewer_available=False,
        )
    pipeline = _build_install_pipeline(config)

    def rewrite() -> None:
        selected = config.targets.configured
        if selected:
            preview = pipeline.preview_reconcile(
                selected,
                selected,
                scope=config.targets.scope,
            )
            result = pipeline.apply_reconcile(preview, confirmed=True)
            if all(result.validations):
                config.targets.configured = list(dict.fromkeys(selected))
                config.targets.last_validated = True
                save_config(path, config)

    def initialize_catalog() -> None:
        CatalogDatabase(config.catalog.database_path).initialize()
        config.catalog.initialized = True
        save_config(path, config)

    return SimpleNamespace(
        config=config,
        config_path=path,
        index_path=config.catalog.database_path,
        reports_path=config.reports.directory,
        catalog_sync_warning=_latest_sync_warning(config.catalog.database_path),
        registry=pipeline.registry,
        rewrite_skillcheck_integration=rewrite,
        initialize_empty_catalog=initialize_catalog,
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
