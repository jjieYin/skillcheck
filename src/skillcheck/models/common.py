from enum import StrEnum


class Provider(StrEnum):
    CODEX = "codex"
    AGENTS = "agents"
    CLAUDE = "claude"
    CURSOR = "cursor"
    CUSTOM = "custom"


class Scope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    CUSTOM = "custom"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(StrEnum):
    PASS = "PASS"
    DUPLICATE = "DUPLICATE"
    SIMILAR = "SIMILAR"
    CONFLICT = "CONFLICT"
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    MERGE = "MERGE"
    VARIANT = "VARIANT"
    DEPRECATE = "DEPRECATE"
    REJECT = "REJECT"
    UNSAFE = "UNSAFE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
