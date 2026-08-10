"""Build bounded, privacy-aware review packets."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field


class ReviewPacket(BaseModel):
    packet_id: str
    groups: list[dict[str, Any]] = Field(default_factory=list)
    allow_full_text: bool = False
    serialized_chars: int = 0


def _redact(value: Any, *, allow_full_text: bool) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).casefold()
            if lowered in {"body", "full_text", "content"} and not allow_full_text:
                result[str(key)] = "[REDACTED]"
                continue
            result[str(key)] = _redact(item, allow_full_text=allow_full_text)
        return result
    if isinstance(value, list):
        return [_redact(item, allow_full_text=allow_full_text) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"(?:sk-[A-Za-z0-9_-]{8,}|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^,;\s]+)",
            "[REDACTED]",
            value,
            flags=re.IGNORECASE,
        )
    return value


def _dump_group(group: Any, *, allow_full_text: bool) -> dict[str, Any]:
    if hasattr(group, "model_dump"):
        payload = group.model_dump(mode="json")
    elif isinstance(group, dict):
        payload = dict(group)
    else:
        payload = {"group_id": str(getattr(group, "group_id", "unknown"))}
        payload.update(
            {
                key: getattr(group, key)
                for key in ("relation", "member_skill_ids", "evidence", "recommendations")
                if hasattr(group, key)
            }
        )
    return _redact(payload, allow_full_text=allow_full_text)


def build_packets(
    groups,
    *,
    max_groups: int = 10,
    max_chars: int = 20_000,
    allow_full_text: bool = False,
) -> list[ReviewPacket]:
    """Split groups into stable bounded packets, excluding exact duplicates."""

    if max_groups < 1 or max_chars < 1:
        raise ValueError("max_groups 和 max_chars 必须为正数")
    packets: list[ReviewPacket] = []
    current: list[dict[str, Any]] = []
    current_size = 2
    packet_number = 1
    for group in groups:
        relation = getattr(group, "relation", None)
        relation_value = getattr(relation, "value", relation)
        if isinstance(group, dict):
            relation_value = group.get("relation")
        if relation_value == "EXACT_DUPLICATE":
            continue
        payload = _dump_group(group, allow_full_text=allow_full_text)
        encoded_size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if current and (len(current) >= max_groups or current_size + encoded_size > max_chars):
            packets.append(
                ReviewPacket(
                    packet_id=f"review-packet-{packet_number:03d}",
                    groups=current,
                    allow_full_text=allow_full_text,
                    serialized_chars=current_size,
                )
            )
            packet_number += 1
            current = []
            current_size = 2
        if encoded_size > max_chars and not current:
            payload = {"group_id": payload.get("group_id", "unknown"), "evidence": ["[REDACTED: packet too large]"]}
            encoded_size = len(json.dumps(payload, ensure_ascii=False))
        current.append(payload)
        current_size += encoded_size + 1
    if current:
        packets.append(
            ReviewPacket(
                packet_id=f"review-packet-{packet_number:03d}",
                groups=current,
                allow_full_text=allow_full_text,
                serialized_chars=current_size,
            )
        )
    return packets

