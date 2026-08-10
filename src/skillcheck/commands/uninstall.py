"""Preview and execute safe program uninstall."""

from __future__ import annotations

from typing import Annotated

import typer

from skillcheck.lifecycle.uninstall import UninstallManager


def build_uninstall_context():
    raise RuntimeError("当前运行时未提供可卸载的自包含安装布局")


def register(app: typer.Typer) -> None:
    @app.command("uninstall")
    def uninstall(
        yes: Annotated[bool, typer.Option("--yes", help="确认执行卸载")] = False,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        try:
            manager = UninstallManager(build_uninstall_context())
            plan = manager.plan()
            if as_json:
                typer.echo(plan.model_dump_json(indent=2))
            else:
                typer.echo("将移除程序路径：")
                for path in plan.exact_paths:
                    typer.echo(f"- {path}")
                typer.echo("默认保留 Skills、索引、报告和用户配置。")
            confirmed = yes or (typer.confirm("确认卸载？") if not as_json else False)
            result = manager.execute(plan, confirmed=confirmed)
            if not as_json:
                typer.echo(getattr(result, "message", "已取消" if not confirmed else "卸载已执行"))
            raise typer.Exit(code=0 if getattr(result, "changed", False) else 1)
        except typer.Exit:
            raise
        except Exception as exc:
            typer.echo(f"卸载失败：{exc}", err=True)
            raise typer.Exit(code=3) from exc

