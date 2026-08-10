"""Instructions exposed to connected Agents."""

MCP_INSTRUCTIONS = """
You are connected to Skillcheck's local Skills-governance service. Use it in
this order: call skillcheck_analyze; select a candidate group and call
skillcheck_evidence for bounded, redacted evidence; then make an explicit
human-readable decision with skillcheck_save_review. You may propose KEEP_BOTH,
MERGE, DEPRECATE, DELETE_DUPLICATE, RENAME, REWRITE_BOUNDARY, or MANUAL_REVIEW.

Skillcheck performs deterministic local analysis and saves governance reports.
It never runs Codex, Claude, or another Agent subprocess, and it never edits,
deletes, renames, or installs the user's Skill files. Evidence page numbers are
zero-based; bodies are optional, redacted, and bounded.
""".strip()
