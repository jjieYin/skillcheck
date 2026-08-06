import typer

from skillcheck import __version__


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Manage a personal local Skill inventory."""


@app.command()
def version() -> None:
    """Print the installed skillcheck version."""
    typer.echo(f"skillcheck {__version__}")
