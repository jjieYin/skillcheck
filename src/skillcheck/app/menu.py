from __future__ import annotations

import sys

import typer


MENU_ITEMS = {
    "1": "扫描现有 Skills",
    "2": "检查并安装新 Skill",
    "3": "查看最近报告",
    "4": "配置 Agent",
    "5": "检查运行环境",
    "6": "卸载 skillcheck（保留数据）",
    "0": "退出",
}


def choose_action() -> str:
    typer.echo("\nSkillcheck")
    for key, label in MENU_ITEMS.items():
        typer.echo(f"  {key}. {label}")
    return typer.prompt("请选择", default="0").strip()


def run_menu() -> None:
    typer.echo("\nSkillcheck")
    for key, label in MENU_ITEMS.items():
        typer.echo(f"  {key}. {label}")
    if not sys.stdin.isatty():
        typer.echo("当前终端不是交互模式，请使用 skillcheck scan 或 skillcheck add SOURCE。")
        return
    while True:
        action = choose_action()
        if action in {"0", "q", "quit", "exit"}:
            typer.echo("已退出。")
            return
        if action == "4":
            typer.echo("请运行 skillcheck setup，进入 Agent 自动检测和配置向导。")
            continue
        if action == "6":
            typer.echo("请运行 skillcheck uninstall，预览精确卸载路径。")
            continue
        typer.echo(f"功能“{MENU_ITEMS.get(action, action)}”将在对应命令中执行。")
