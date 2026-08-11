"""Preview and execute removal of Skillcheck-owned integrations."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated

import typer

from skillcheck.commands.install import _build_install_pipeline
from skillcheck.config import app_home, load_config
from skillcheck.lifecycle.uninstall import UninstallManager


def build_uninstall_context():
    config = load_config(create=False)
    pipeline = _build_install_pipeline(config)
    selected = [pipeline.registry.get(agent) for agent in config.targets.configured]
    home = app_home()
    return SimpleNamespace(
        targets=SimpleNamespace(configured=lambda: selected),
        agent_scope=config.targets.scope,
        layout=SimpleNamespace(owned_program_paths=list, owned_roots=lambda: [home]),
        helpers=SimpleNamespace(remove_program_after_exit=lambda _paths: None),
        data=SimpleNamespace(remove_selected=lambda _plan: None),
    )


def register(app: typer.Typer) -> None:
    @app.command("uninstall")
    def uninstall(
        yes: Annotated[bool, typer.Option("--yes")] = False,
        keep_cli: Annotated[bool, typer.Option("--keep-cli")] = False,
        keep_data: Annotated[bool, typer.Option("--keep-data")] = False,
        complete: Annotated[bool, typer.Option("--complete")] = False,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        try:
            manager = UninstallManager(build_uninstall_context())
            plan = manager.plan(keep_cli=keep_cli, keep_data=keep_data, complete=complete)
            if as_json:
                typer.echo(plan.model_dump_json(indent=2))
                raise typer.Exit(code=0)
            for path in plan.exact_paths:
                typer.echo(f"- {path}")
            confirmed = yes or typer.confirm("Remove only Skillcheck-owned integrations?")
            result = manager.execute(plan, confirmed=confirmed)
            typer.echo(result.message)
            raise typer.Exit(code=0 if result.changed else 1)
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"uninstall failed: {exc}", err=True)
            raise typer.Exit(code=3) from exc
