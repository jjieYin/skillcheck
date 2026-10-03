"""Upgrade and rollback command."""

from __future__ import annotations

import typer

from skillcheck.lifecycle.release_client import ReleaseClient
from skillcheck.lifecycle.upgrade import LocalUpgradeContext, UpgradeManager


def build_upgrade_context():
    context = LocalUpgradeContext()
    context.release_client = ReleaseClient()
    return context


def register(app: typer.Typer) -> None:
    @app.command("upgrade")
    def upgrade(
        version: str = typer.Argument(None),
        rollback: bool = typer.Option(False, "--rollback"),
        yes: bool = typer.Option(False, "--yes"),
        as_json: bool = typer.Option(False, "--json"),
    ) -> None:
        del yes
        try:
            manager = UpgradeManager(build_upgrade_context())
            result = manager.rollback() if rollback else manager.install(version or "latest")
            if as_json and hasattr(result, "model_dump_json"):
                typer.echo(result.model_dump_json())
            else:
                typer.echo(getattr(result, "message", "升级完成"))
            raise typer.Exit(code=0 if getattr(result, "changed", False) else 1)
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"升级失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc
