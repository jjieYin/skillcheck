"""Read-only MCP integration for local skill governance reports."""

from skillcheck.mcp.server import TOOL_NAMES, create_server
from skillcheck.mcp.tools import SkillcheckQueries

__all__ = ["TOOL_NAMES", "SkillcheckQueries", "create_server"]

