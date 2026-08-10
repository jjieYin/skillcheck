"""Read-only environment diagnostics and explicit repair plans."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


class DoctorCheck(BaseModel):
    code: str
    status: CheckStatus
    message: str
    remediation: str | None = None
    sensitive: bool = False


class DoctorReport(BaseModel):
    checks: list[DoctorCheck] = Field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if any(item.status is CheckStatus.ERROR for item in self.checks):
            return 2
        if any(item.status is CheckStatus.WARNING for item in self.checks):
            return 1
        return 0


class FixPlan(BaseModel):
    actions: list[str] = Field(default_factory=list)


REQUIRED_CODES = (
    "runtime.version",
    "path.shadowing",
    "config.parse",
    "database.integrity",
    "reports.permissions",
    "targets.detect",
    "reviewers.detect",
    "mcp.handshake",
)


class Doctor:
    def __init__(self, context: Any) -> None:
        self.context = context

    def run(self, *, fix: bool = False) -> DoctorReport:
        # ``fix`` is intentionally accepted for API compatibility but never
        # writes. The command layer must obtain confirmation and call apply().
        del fix
        checks = [
            self._runtime(),
            self._path_shadowing(),
            self._config_parse(),
            self._database_integrity(),
            self._reports_permissions(),
            self._targets_detect(),
            self._reviewers_detect(),
            self._mcp_handshake(),
        ]
        return DoctorReport(checks=checks)

    def plan(self, report: DoctorReport) -> FixPlan:
        actions: list[str] = []
        allowed = {
            "path.shadowing": "restore_launcher_path",
            "database.integrity": "rebuild_index",
            "mcp.handshake": "rewrite_skillcheck_mcp",
        }
        for check in report.checks:
            action = allowed.get(check.code)
            fixable = check.status is CheckStatus.ERROR or (
                check.code in {"path.shadowing", "mcp.handshake"} and check.status is CheckStatus.WARNING
            )
            if action and fixable:
                actions.append(action)
        return FixPlan(actions=actions)

    def apply(self, plan: FixPlan) -> list[str]:
        """Apply only named, context-provided repair hooks."""

        completed: list[str] = []
        hooks = {
            "restore_launcher_path": "restore_launcher_path",
            "rebuild_index": "rebuild_index",
            "rewrite_skillcheck_mcp": "rewrite_skillcheck_mcp",
        }
        for action in plan.actions:
            hook_name = hooks[action]
            hook = getattr(self.context, hook_name, None)
            if callable(hook):
                hook()
                completed.append(action)
        return completed

    def _runtime(self) -> DoctorCheck:
        version = getattr(self.context, "python_version", None) or sys.version_info[:3]
        ok = tuple(version) >= (3, 11)
        return DoctorCheck(
            code="runtime.version",
            status=CheckStatus.OK if ok else CheckStatus.ERROR,
            message=f"Python {version[0]}.{version[1]} 可用" if ok else "需要 Python 3.11 或更高版本",
            remediation=None if ok else "升级 Python 运行时",
        )

    def _path_shadowing(self) -> DoctorCheck:
        explicit = getattr(self.context, "path_shadowing", None)
        if explicit is True:
            return DoctorCheck(
                code="path.shadowing",
                status=CheckStatus.WARNING,
                message="PATH 中存在遮蔽 skillcheck 的旧启动器",
                remediation="重新安装稳定启动器并确认 PATH 顺序",
            )
        if explicit is False:
            return DoctorCheck(code="path.shadowing", status=CheckStatus.OK, message="未发现 PATH 遮蔽")
        executable = shutil.which("skillcheck")
        return DoctorCheck(
            code="path.shadowing",
            status=CheckStatus.OK if executable else CheckStatus.WARNING,
            message="已找到 skillcheck 启动器" if executable else "未在 PATH 中找到 skillcheck 启动器",
            remediation=None if executable else "安装自包含启动器或使用开发环境入口",
        )

    def _config_parse(self) -> DoctorCheck:
        error = getattr(self.context, "config_error", None)
        if error:
            return DoctorCheck(
                code="config.parse",
                status=CheckStatus.ERROR,
                message="配置文件无法解析",
                remediation="备份后修复 YAML 配置，再重新运行 doctor",
            )
        config_path = getattr(self.context, "config_path", None)
        if config_path and Path(config_path).exists():
            try:
                import yaml

                payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
                if payload is not None and not isinstance(payload, dict):
                    raise ValueError("root")
            except Exception:
                return DoctorCheck(
                    code="config.parse",
                    status=CheckStatus.ERROR,
                    message="配置文件无法解析",
                    remediation="备份后修复 YAML 配置，再重新运行 doctor",
                )
            return DoctorCheck(code="config.parse", status=CheckStatus.OK, message="配置文件可解析")
        return DoctorCheck(
            code="config.parse",
            status=CheckStatus.WARNING,
            message="尚未发现配置文件，将使用默认配置",
            remediation="运行 skillcheck setup 初始化配置",
        )

    def _database_integrity(self) -> DoctorCheck:
        explicit = getattr(self.context, "database_integrity", None)
        if explicit is False:
            return DoctorCheck(
                code="database.integrity",
                status=CheckStatus.ERROR,
                message="索引数据库完整性检查失败",
                remediation="确认后重建本地索引",
            )
        path = getattr(self.context, "index_path", None)
        if not path or not Path(path).exists():
            return DoctorCheck(
                code="database.integrity",
                status=CheckStatus.WARNING,
                message="尚未建立索引数据库",
                remediation="运行 skillcheck scan 建立索引",
            )
        try:
            with sqlite3.connect(path) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error:
            result = "error"
        return DoctorCheck(
            code="database.integrity",
            status=CheckStatus.OK if result == "ok" else CheckStatus.ERROR,
            message="索引数据库完整" if result == "ok" else "索引数据库完整性检查失败",
            remediation=None if result == "ok" else "确认后重建本地索引",
        )

    def _reports_permissions(self) -> DoctorCheck:
        path = getattr(self.context, "reports_path", None)
        if not path:
            return DoctorCheck(code="reports.permissions", status=CheckStatus.WARNING, message="未配置报告目录")
        report_path = Path(path)
        if report_path.exists() and os.access(report_path, os.W_OK):
            return DoctorCheck(code="reports.permissions", status=CheckStatus.OK, message="报告目录可写")
        return DoctorCheck(
            code="reports.permissions",
            status=CheckStatus.WARNING,
            message="报告目录不存在或不可写",
            remediation="确认后创建报告目录或修复权限",
        )

    def _targets_detect(self) -> DoctorCheck:
        explicit = getattr(self.context, "targets_detected", None)
        if explicit is False:
            return DoctorCheck(
                code="targets.detect",
                status=CheckStatus.WARNING,
                message="未检测到可用 Agent",
                remediation="运行 skillcheck setup 选择 Agent",
            )
        registry = getattr(self.context, "registry", None)
        if registry is None:
            return DoctorCheck(code="targets.detect", status=CheckStatus.WARNING, message="未执行 Agent 检测")
        try:
            detections = registry.detect_all()
            detected = [item for item in detections if item.cli_path or item.config_path]
        except Exception:
            detected = []
        return DoctorCheck(
            code="targets.detect",
            status=CheckStatus.OK if detected else CheckStatus.WARNING,
            message=f"已检测到 {len(detected)} 个 Agent" if detected else "未检测到可用 Agent",
            remediation=None if detected else "运行 skillcheck setup 选择 Agent",
        )

    def _reviewers_detect(self) -> DoctorCheck:
        available = getattr(self.context, "reviewer_available", None)
        if available is None:
            available = getattr(self.context, "reviewer", None) is not None
        return DoctorCheck(
            code="reviewers.detect",
            status=CheckStatus.OK if available else CheckStatus.WARNING,
            message="已配置可选 Agent 复核" if available else "未配置 Agent 复核（基础检查仍可运行）",
            remediation=None if available else "按需配置 Codex 或 Claude 复核",
        )

    def _mcp_handshake(self) -> DoctorCheck:
        explicit = getattr(self.context, "mcp_available", None)
        if explicit is None:
            try:
                from skillcheck.mcp.server import TOOL_NAMES

                explicit = len(TOOL_NAMES) == 3
            except Exception:
                explicit = False
        return DoctorCheck(
            code="mcp.handshake",
            status=CheckStatus.OK if explicit else CheckStatus.WARNING,
            message="只读 MCP 服务可加载" if explicit else "只读 MCP 服务不可用",
            remediation=None if explicit else "安装 MCP 依赖后重试",
        )
