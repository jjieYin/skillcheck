"""Preview and execute removal of Skillcheck-owned integrations."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

from skillcheck.commands.install import _build_install_pipeline
from skillcheck.config import app_home, load_config
from skillcheck.lifecycle.uninstall import UninstallManager
from skillcheck.lifecycle.upgrade import LocalUpgradeLayout


def build_uninstall_context():
    config = load_config(create=False)
    pipeline = _build_install_pipeline(config)
    selected = [pipeline.registry.get(agent) for agent in config.targets.configured]
    data_root = app_home().resolve(strict=False)
    layout = LocalUpgradeLayout()
    program_root = layout.root.expanduser().resolve(strict=False)

    def remove_paths(paths) -> list[str]:
        removed: list[str] = []
        scheduled: list[str] = []
        for raw in paths:
            path = Path(raw).expanduser()
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                    removed.append(str(path))
                elif path.exists() or path.is_symlink():
                    path.unlink()
                    removed.append(str(path))
            except OSError as error:
                locked = isinstance(error, PermissionError) or getattr(error, "winerror", None) in {5, 32}
                if os.name != "nt" or not locked:
                    raise
                _schedule_windows_removal(path)
                scheduled.append(str(path))
        return SimpleNamespace(removed=removed, scheduled=scheduled)

    def remove_data(plan) -> list[str]:
        del plan
        return remove_paths([data_root])

    return SimpleNamespace(
        targets=SimpleNamespace(configured=lambda: selected),
        agent_scope=config.targets.scope,
        layout=SimpleNamespace(
            owned_program_paths=lambda: [program_root],
            owned_data_paths=lambda: [data_root],
            owned_roots=lambda: [program_root, data_root],
        ),
        helpers=SimpleNamespace(remove_program_after_exit=remove_paths),
        data=SimpleNamespace(remove_selected=remove_data),
    )


def _schedule_windows_removal(path: Path) -> None:
    """Remove a locked portable-install directory after this executable exits."""

    literal = str(path.resolve(strict=False)).replace("'", "''")
    command = (
        "Start-Sleep -Seconds 1; "
        f"Remove-Item -LiteralPath '{literal}' -Recurse -Force -ErrorAction Stop"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
