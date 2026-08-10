"""Application package.

The entry point is imported lazily so command modules can safely import
``skillcheck.app.context`` without recursively importing the root Typer app.
"""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from skillcheck.app.main import app

        return app
    raise AttributeError(name)
