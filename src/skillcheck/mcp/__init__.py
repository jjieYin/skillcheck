"""Agent-native MCP integration for local Skills governance."""

from typing import Any

__all__ = ["TOOL_NAMES", "SkillcheckMcpTools", "create_server"]


def __getattr__(name: str) -> Any:
    """Avoid importing the server while governance loads its runtime type."""
    if name in {"TOOL_NAMES", "create_server"}:
        from skillcheck.mcp.server import TOOL_NAMES, create_server

        return {"TOOL_NAMES": TOOL_NAMES, "create_server": create_server}[name]
    if name == "SkillcheckMcpTools":
        from skillcheck.mcp.tools import SkillcheckMcpTools

        return SkillcheckMcpTools
    raise AttributeError(name)
