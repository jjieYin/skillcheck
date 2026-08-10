"""Safe, format-aware configuration editing primitives for Agent adapters."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from tomlkit import TOMLDocument, dumps, parse, table


class ConfigFormatError(RuntimeError):
    """Raised when an Agent configuration cannot be parsed safely."""


@dataclass(frozen=True)
class ConfigWriteResult:
    path: Path
    changed: bool
    summary: tuple[str, ...] = ()


def content_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest() if data else None


def atomic_replace(path: Path, content: str, *, expected_hash: str | None) -> None:
    """Replace a config only when it still has the hash shown in the preview."""

    current = path.read_bytes() if path.exists() else b""
    current_hash = hashlib.sha256(current).hexdigest() if current else None
    if current_hash != expected_hash:
        raise RuntimeError(f"配置在确认后发生变化：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".skillcheck.bak")
    if path.exists():
        backup.write_bytes(current)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.skillcheck-",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def load_document(path: Path, fmt: Literal["json", "toml"]) -> tuple[Any, str, str | None]:
    """Load a JSON/TOML document and return document, source text and hash."""

    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        if fmt == "json":
            document = json.loads(text) if text.strip() else {}
        else:
            document = parse(text) if text.strip() else TOMLDocument()
    except Exception as exc:
        raise ConfigFormatError(f"无法解析 {fmt.upper()} 配置：{path}；未写入文件") from exc
    if not isinstance(document, (dict, TOMLDocument)):
        raise ConfigFormatError(f"配置根节点必须是对象：{path}")
    return document, text, content_hash(path)


def render_document(document: Any, fmt: Literal["json", "toml"]) -> str:
    if fmt == "json":
        return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    return dumps(document)


def read_mcp_entry(document: Any, fmt: Literal["json", "toml"], key: str) -> Any:
    container_key = "mcpServers" if fmt == "json" else "mcp_servers"
    container = document.get(container_key, {})
    return container.get(key) if hasattr(container, "get") else None


def write_mcp_entry(
    document: Any,
    fmt: Literal["json", "toml"],
    key: str,
    entry: dict[str, Any] | None,
) -> None:
    container_key = "mcpServers" if fmt == "json" else "mcp_servers"
    if container_key not in document:
        document[container_key] = {} if fmt == "json" else table()
    container = document[container_key]
    if entry is None:
        if hasattr(container, "pop"):
            container.pop(key, None)
        return
    if fmt == "toml":
        value = table()
        for name, item in entry.items():
            value[name] = item
        container[key] = value
    else:
        container[key] = entry


def mcp_entry_matches(existing: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(existing, dict):
        return False
    return existing.get("command") == expected["command"] and existing.get("args") == expected["args"]
