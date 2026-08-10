from __future__ import annotations

import typer

from skillcheck import __version__
from skillcheck.commands.report import register as register_report
from skillcheck.commands.scan import register as register_scan


app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Manage the personal local Skill inventory."""
    if ctx.invoked_subcommand is None:
        from skillcheck.app.menu import run_menu

        run_menu()


@app.command()
def version() -> None:
    """Print the installed skillcheck version."""
    typer.echo(f"skillcheck {__version__}")


register_scan(app)
register_report(app)
