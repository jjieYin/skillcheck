"""Run a small, privacy-preserving acceptance check for Agent trigger policy.

The harness is deliberately independent of a particular Agent.  A caller provides
an executable command template containing ``{prompt}``; the Agent's JSON/event
output is reduced to the Skillcheck tool names that occurred.  Prompts and model
thinking are never written to the result file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SKILLCHECK_TOOLS = (
    "skillcheck_analyze",
    "skillcheck_evidence",
    "skillcheck_save_review",
    "skillcheck_save_sync_group",
)
_TOOL_RE = re.compile(r"\b(skillcheck_(?:analyze|evidence|save_review|save_sync_group))\b")
_GROUP_KEYS = {"groups", "candidate_groups"}
_EMPTY_ANALYSIS_ERROR = "evidence called after empty analysis"
_EMPTY_REVIEW_ERROR = "review saved after empty analysis"


@dataclass(frozen=True)
class _TraceRecord:
    value: Any | None
    raw: str


def _read_trace(trace: Path | str | Iterable[str]) -> list[_TraceRecord]:
    """Read JSONL/event output without retaining unparsed model text."""

    if isinstance(trace, (str, Path)):
        text = Path(trace).read_text(encoding="utf-8")
        lines: Iterable[str] = text.splitlines()
    else:
        lines = trace
    records: list[_TraceRecord] = []
    for line in lines:
        raw = str(line).strip()
        if not raw:
            continue
        try:
            records.append(_TraceRecord(json.loads(raw), raw))
        except json.JSONDecodeError:
            # Some Agent CLIs mix human-readable lines with JSON events.  Keep
            # only the short line needed for tool-name detection.
            records.append(_TraceRecord(None, raw))
    return records


def _tool_names(value: Any) -> list[str]:
    """Extract known tool names from nested event objects in encounter order."""

    found: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if (
                    key in {"tool", "tool_name", "name", "method"}
                    and isinstance(nested, str)
                    and nested in SKILLCHECK_TOOLS
                    and nested not in found
                ):
                    found.append(nested)
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return found


def _record_tools(record: _TraceRecord) -> list[str]:
    found = _tool_names(record.value)
    # For valid JSON, inspect event fields rather than arbitrary message text;
    # a prompt mentioning a tool must not count as an invocation.  Plain text
    # lines are supported as a conservative fallback for CLIs that mix output.
    if record.value is None:
        for match in _TOOL_RE.findall(record.raw):
            if match not in found:
                found.append(match)
    return found


def _contains_empty_groups(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _GROUP_KEYS and isinstance(nested, list) and not nested:
                return True
            if _contains_empty_groups(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_empty_groups(nested) for nested in value)
    return False


def tool_sequence(trace: Path | str | Iterable[str]) -> list[str]:
    """Return the ordered Skillcheck tool names found in an Agent trace."""

    sequence: list[str] = []
    for record in _read_trace(trace):
        sequence.extend(_record_tools(record))
    return sequence


def observed_policy(trace: Path | str | Iterable[str]) -> str:
    """Classify a trace as ``call`` or ``no_call``."""

    return "call" if tool_sequence(trace) else "no_call"


def validate_trace(trace: Path | str | Iterable[str]) -> list[str]:
    """Validate follow-up ordering and empty-analysis behavior.

    An empty candidate list is terminal: evidence and persistence tools must not
    be called until another analysis produces candidates.
    """

    errors: list[str] = []
    empty_analysis = False
    for record in _read_trace(trace):
        tools = _record_tools(record)
        has_empty_groups = _contains_empty_groups(record.value)
        for tool in tools:
            if tool == "skillcheck_analyze":
                empty_analysis = has_empty_groups
            elif empty_analysis and tool == "skillcheck_evidence":
                if _EMPTY_ANALYSIS_ERROR not in errors:
                    errors.append(_EMPTY_ANALYSIS_ERROR)
            elif (
                empty_analysis
                and tool in {"skillcheck_save_review", "skillcheck_save_sync_group"}
                and _EMPTY_REVIEW_ERROR not in errors
            ):
                errors.append(_EMPTY_REVIEW_ERROR)
    return errors


def _quote_prompt(prompt: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([prompt])
    return shlex.quote(prompt)


def _render_command(command: str, prompt: str) -> str:
    rendered = command.replace("{prompt}", _quote_prompt(prompt))
    if rendered == command:
        rendered = f"{command} {_quote_prompt(prompt)}"
    return rendered


def _run_agent(command: str, prompt: str, timeout: int = 180) -> tuple[int | None, str]:
    try:
        completed = subprocess.run(
            _render_command(command, prompt),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = "\n".join(
            part.decode("utf-8", "replace") if isinstance(part, bytes) else str(part)
            for part in (error.stdout or "", error.stderr or "")
        )
        return None, output
    return completed.returncode, "\n".join(part for part in (completed.stdout, completed.stderr) if part)


def run_cases(agent: str, command: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        expected = str(case.get("expect", "no_call"))
        prompt = str(case.get("prompt", ""))
        exit_code, output = _run_agent(command, prompt)
        # Use a temporary trace-like in-memory sequence.  The output is not
        # included in the report, only the extracted tool names and short errors.
        lines = output.splitlines()
        tools = tool_sequence(lines)
        errors = validate_trace(lines)
        observed = "call" if tools else "no_call"
        results.append(
            {
                "id": case_id,
                "expected": expected,
                "observed": observed,
                "pass": observed == expected and not errors,
                "tools": tools,
                "trace_errors": errors,
                "exit_code": exit_code,
            }
        )
    return {
        "agent": agent,
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": results,
        "passed": all(result["pass"] for result in results),
    }


def _load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(case, dict) for case in data):
        raise ValueError("cases must be a JSON array of objects")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, help="Agent label, for example codex")
    parser.add_argument("--command", required=True, help="Agent command template; use {prompt}")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_cases(args.agent, args.command, _load_cases(args.cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"agent": args.agent, "passed": report["passed"], "output": str(args.output)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
