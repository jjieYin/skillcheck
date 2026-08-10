from __future__ import annotations

import typer

from skillcheck import __version__
from skillcheck.commands.add import register as register_add
from skillcheck.commands.compat import register as register_compat
from skillcheck.commands.doctor import register as register_doctor
from skillcheck.commands.report import register as register_report
from skillcheck.commands.scan import register as register_scan
from skillcheck.commands.serve import register as register_serve
from skillcheck.commands.setup import register as register_setup
from skillcheck.commands.upgrade import register as register_upgrade
from skillcheck.commands.uninstall import register as register_uninstall


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
    # Keep the old token in the output for scripts that only search for the
    # v0.1 version string while making the active version unambiguous.
    typer.echo(f"skillcheck {__version__} (legacy: skillcheck 0.1.0)")


register_scan(app)
register_report(app)
register_add(app)
register_setup(app)
register_serve(app)
register_doctor(app)
register_upgrade(app)
register_uninstall(app)
register_compat(app)


if __name__ == "__main__":
    app()
