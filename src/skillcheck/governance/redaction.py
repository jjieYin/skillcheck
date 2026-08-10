from __future__ import annotations

import re
from typing import Any

_FIELD = re.compile(
    r"(?i)(?P<label>\b(?:api[_-]?key|token|secret|password)\b)\s*(?P<separator>[:=])\s*"
    r"(?P<quote>['\"]?)(?P<value>[^\s,'\";]+)(?P<endquote>['\"]?)"
)
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")


def redact_text(text: str) -> str:
    """Remove credential values while preserving field labels and delimiters."""
    redacted = _FIELD.sub(lambda match: f"{match.group('label')}{match.group('separator')} [REDACTED]", text)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
    return _SK_TOKEN.sub("[REDACTED]", redacted)


def redact_value(value: Any) -> Any:
    """Recursively sanitize report/review payloads without changing their shape."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value
