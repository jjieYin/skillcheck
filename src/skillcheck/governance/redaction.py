from __future__ import annotations

import re
from typing import Any

_FIELD_START = re.compile(
    r"(?i)(?P<label>\b(?:api[_-]?key|token|secret|password)\b)\s*"
    r"(?P<separator>[:=])\s*"
)
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")


def redact_text(text: str) -> str:
    """Remove credential values while preserving field labels and delimiters."""
    pieces: list[str] = []
    cursor = 0
    for match in _FIELD_START.finditer(text):
        if match.start() < cursor:
            continue
        pieces.append(text[cursor : match.start()])
        pieces.append(f"{match.group('label')}{match.group('separator')} [REDACTED]")
        cursor = _credential_end(text, match.end())
    pieces.append(text[cursor:])
    redacted = "".join(pieces)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
    return _SK_TOKEN.sub("[REDACTED]", redacted)


def _credential_end(text: str, start: int) -> int:
    if start >= len(text):
        return start
    if text[start] not in "'\"":
        end = start
        while end < len(text) and not (text[end].isspace() or text[end] in ",;\"'"):
            end += 1
        return end

    quote = text[start]
    candidate = _next_unescaped_quote(text, start + 1, quote)
    if candidate < 0:
        line_end = text.find("\n", start + 1)
        return len(text) if line_end < 0 else line_end
    # A quote after a later sensitive field is likely that field's opening quote,
    # not the end of this malformed value. Redact only this line and process the
    # following field independently.
    nested = _FIELD_START.search(text, start + 1, candidate)
    if nested is not None and "\n" in text[start + 1 : nested.start() + 1]:
        line_end = text.find("\n", start + 1)
        return len(text) if line_end < 0 else line_end
    return candidate + 1


def _next_unescaped_quote(text: str, start: int, quote: str) -> int:
    position = start
    while True:
        position = text.find(quote, position)
        if position < 0:
            return -1
        backslashes = 0
        index = position - 1
        while index >= 0 and text[index] == "\\":
            backslashes += 1
            index -= 1
        if backslashes % 2 == 0:
            return position
        position += 1


def redact_value(value: Any) -> Any:
    """Recursively sanitize report/review payloads without changing their shape."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value
