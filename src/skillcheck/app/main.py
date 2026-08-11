from __future__ import annotations

import typer

from skillcheck import __version__
from skillcheck.commands.add import register as register_add
from skillcheck.commands.doctor import register as register_doctor
from skillcheck.commands.init import register as register_init
from skillcheck.commands.install import register as register_install
from skillcheck.commands.report import register as register_report
from skillcheck.commands.scan import register as register_scan
from skillcheck.commands.serve import register as register_serve
from skillcheck.commands.status import read_status, render_status
from skillcheck.commands.status import register as register_status
from skillcheck.commands.sync import register as register_sync
from skillcheck.commands.uninstall import register as register_uninstall
from skillcheck.commands.upgrade import register as register_upgrade

app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Manage the personal local Skill inventory."""
    if ctx.invoked_subcommand is None:
        status = read_status()
        if not status.configured_agents:
            typer.echo("配置 Skillcheck Agent 接入")
            typer.echo("运行 skillcheck install，选择需要接入的 Codex、Claude Code 或 Cursor。")
            return
        typer.echo(render_status(status))


@app.command()
def version() -> None:
    """Print the installed skillcheck version."""
    typer.echo(f"skillcheck {__version__}")


register_scan(app)
register_report(app)
register_add(app)
register_serve(app)
register_doctor(app)
register_upgrade(app)
register_uninstall(app)
register_init(app)
register_sync(app)
register_install(app)
register_status(app)


if __name__ == "__main__":
    app()
