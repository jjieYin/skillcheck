"""Preview and execute removal of Skillcheck-owned integrations."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

from skillcheck.commands.install import SUPPORTED_TARGETS, _build_install_pipeline
from skillcheck.config import app_home, load_config, save_config
from skillcheck.lifecycle.uninstall import RemovalOutcome, UninstallManager
from skillcheck.lifecycle.upgrade import LocalUpgradeLayout


def build_uninstall_context(
    config_path: Path | None = None,
    *,
    target_names: list[str] | None = None,
):
    config = load_config(config_path, create=False)
    pipeline = _build_install_pipeline(config)
    selected_names = list(config.targets.configured) if target_names is None else list(target_names)
    selected = [pipeline.registry.get(agent) for agent in selected_names]
    data_root = app_home().resolve(strict=False)
    layout = LocalUpgradeLayout()
    program_root = layout.root.expanduser().resolve(strict=False)

    def remove_paths(paths, *, path_entry: Path | None = None) -> RemovalOutcome:
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
                _schedule_windows_removal(path, path_entry)
                scheduled.append(str(path))
        if path_entry is not None and os.name == "nt" and not scheduled:
            _remove_windows_user_path_entry(path_entry)
        return RemovalOutcome(removed=removed, scheduled=scheduled)

    def remove_program(paths) -> RemovalOutcome:
        return remove_paths(paths, path_entry=program_root / "bin")

    def remove_data(plan) -> RemovalOutcome:
        del plan
        return remove_paths([data_root])

    return SimpleNamespace(
        targets=SimpleNamespace(configured=lambda: selected),
        configured_names=list(config.targets.configured),
        selected_names=selected_names,
        config_path=config_path,
        agent_scope=config.targets.scope,
        layout=SimpleNamespace(
            owned_program_paths=lambda: [program_root],
            owned_data_paths=lambda: [data_root],
            owned_roots=lambda: [program_root, data_root],
        ),
        helpers=SimpleNamespace(remove_program_after_exit=remove_program),
        data=SimpleNamespace(remove_selected=remove_data),
    )


def _selected_targets(requested: str | None, configured: list[str]) -> list[str]:
    """Normalize an uninstall selector without widening the removal scope."""

    if requested is None or requested.strip().casefold() in {"", "all"}:
        return list(dict.fromkeys(configured))
    selected = [part.strip().casefold() for part in requested.split(",") if part.strip()]
    invalid = [item for item in selected if item not in SUPPORTED_TARGETS]
    if invalid:
        allowed = ", ".join((*SUPPORTED_TARGETS, "all"))
        raise ValueError(f"--target must be one of: {allowed}")
    return list(dict.fromkeys(selected))


def _remove_configured_targets(config_path: Path | None, selected: list[str]) -> None:
    """Forget selected integrations while preserving the rest of the config."""

    if not selected:
        return
    loaded = load_config(config_path, create=False)
    before = list(loaded.targets.configured)
    remaining = [agent for agent in before if agent not in selected]
    if remaining == before:
        return
    loaded.targets.configured = remaining
    loaded.targets.last_validated = bool(remaining)
    save_config(_config_path(config_path), loaded)


def _config_path(path: Path | None) -> Path:
    return path.expanduser() if path is not None else app_home() / "config.yaml"


def _schedule_windows_removal(path: Path, path_entry: Path | None = None) -> None:
    """Remove a locked portable-install directory after this executable exits."""

    command = _windows_removal_command(path, path_entry)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _remove_windows_user_path_entry(path_entry: Path) -> None:
    """Remove only Skillcheck's portable launcher directory from the User PATH."""

    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            _windows_path_cleanup_command(path_entry),
        ],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _windows_removal_command(path: Path, path_entry: Path | None) -> str:
    literal = _powershell_literal(path)
    command = (
        "Start-Sleep -Seconds 1; "
        f"if (Test-Path -LiteralPath '{literal}') {{ "
        f"Remove-Item -LiteralPath '{literal}' -Recurse -Force -ErrorAction Stop }}"
    )
    return f"{command}; {_windows_path_cleanup_command(path_entry)}" if path_entry else command


def _windows_path_cleanup_command(path_entry: Path) -> str:
    literal = _powershell_literal(path_entry)
    return (
        f"$pathEntry = '{literal}'; "
        "$userPath = [Environment]::GetEnvironmentVariable('Path', 'User'); "
        "$parts = @($userPath -split ';' | Where-Object { $_ -and "
        "$_.TrimEnd('\\') -ine $pathEntry.TrimEnd('\\') }); "
        "[Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User')"
    )


def _powershell_literal(path: Path) -> str:
    return str(path.resolve(strict=False)).replace("'", "''")


def register(app: typer.Typer) -> None:
    @app.command("uninstall")
    def uninstall(
        target: Annotated[
            str | None,
            typer.Option("--target", help="Remove only the selected Agent integration(s)"),
        ] = None,
        yes: Annotated[bool, typer.Option("--yes")] = False,
        keep_cli: Annotated[bool, typer.Option("--keep-cli")] = False,
        keep_data: Annotated[bool, typer.Option("--keep-data")] = False,
        complete: Annotated[bool, typer.Option("--complete")] = False,
        as_json: Annotated[bool, typer.Option("--json")] = False,
        config: Annotated[Path | None, typer.Option("--config")] = None,
    ) -> None:
        try:
            if target is not None and complete:
                raise ValueError("--target cannot be combined with --complete")
            initial = load_config(config, create=False)
            selected_names = _selected_targets(target, list(initial.targets.configured))
            context = build_uninstall_context(config, target_names=selected_names)
            manager = UninstallManager(context)
            plan = manager.plan(keep_cli=keep_cli, keep_data=keep_data, complete=complete)
            if as_json:
                typer.echo(plan.model_dump_json(indent=2))
                raise typer.Exit(code=0)
            for path in plan.exact_paths:
                typer.echo(f"- {path}")
            confirmed = yes or typer.confirm("Remove only Skillcheck-owned integrations?")
            result = manager.execute(plan, confirmed=confirmed)
            if confirmed and target is not None and not complete:
                _remove_configured_targets(config, selected_names)
            typer.echo(result.message)
            raise typer.Exit(code=0 if result.changed else 1)
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"uninstall failed: {exc}", err=True)
            raise typer.Exit(code=3) from exc
