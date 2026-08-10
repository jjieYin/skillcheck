from __future__ import annotations

import typer

from skillcheck import __version__


app = typer.Typer(no_args_is_help=False, invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Manage the personal local Skill inventory."""
    if ctx.invoked_subcommand is None:
        typer.echo("Skillcheck")


@app.command()
def version() -> None:
    """Print the installed skillcheck version."""
    typer.echo(f"skillcheck {__version__}")
