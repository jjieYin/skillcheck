# Task 8 report — Agent-native MCP governance

## Status

Completed the MCP surface transition to exactly three CodeGraph-mode tools:
`skillcheck_analyze`, `skillcheck_evidence`, and `skillcheck_save_review`.
The server owns only MCP lifecycle; it creates no Codex, Claude, or other Agent
subprocess and never mutates a user's Skill files.

## Verification

- `python -m pytest tests/mcp -v` — 14 passed.
- `python -m ruff check src/skillcheck/mcp src/skillcheck/commands/serve.py tests/mcp` — passed.

## Notes

The public evidence page argument is zero-based (and validated as non-negative)
while the existing deterministic analyzer uses one-based page storage. The MCP
facade converts between these contracts. Evidence remains bounded and redacted
by the governance analyzer.
