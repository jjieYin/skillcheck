"""Unit tests for the optional Agent trigger-policy acceptance harness."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_trigger_policy import observed_policy, tool_sequence, validate_trace


def test_harness_classifies_mcp_trace(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"tool":"skillcheck_analyze"}\n', encoding="utf-8")
    assert observed_policy(trace) == "call"
    assert tool_sequence(trace) == ["skillcheck_analyze"]


def test_harness_rejects_evidence_after_empty_analysis(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            [
                json.dumps({"tool": "skillcheck_analyze", "result": {"groups": []}}),
                json.dumps({"tool": "skillcheck_evidence"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert validate_trace(trace) == ["evidence called after empty analysis"]


def test_harness_allows_evidence_after_non_empty_analysis(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        '{"tool":"skillcheck_analyze","result":{"groups":[{"group_id":"g1"}]}}\n'
        '{"tool":"skillcheck_evidence"}\n',
        encoding="utf-8",
    )
    assert validate_trace(trace) == []


def test_harness_ignores_unrelated_tool_names() -> None:
    trace = [
        '{"message":"the prompt mentioned skillcheck_analyze but no tool was called"}',
        '{"name":"other_tool"}',
    ]
    assert observed_policy(trace) == "no_call"
