"""Agent target contracts and detection registry."""

from skillcheck.targets.base import AgentId, AgentTarget, ConfigChange, DetectionResult
from skillcheck.targets.claude import ClaudeTarget
from skillcheck.targets.codex import CodexTarget
from skillcheck.targets.cursor import CursorTarget
from skillcheck.targets.registry import TargetRegistry

__all__ = [
    "AgentId",
    "AgentTarget",
    "ClaudeTarget",
    "CodexTarget",
    "ConfigChange",
    "CursorTarget",
    "DetectionResult",
    "TargetRegistry",
]
