"""Instructions exposed to connected Agents."""

MCP_INSTRUCTIONS = """
Only use Skillcheck when the user's request concerns local Skill inventory,
duplication, overlap, conflicts, installation preflight, cross-Agent mirrors,
sync groups, or Skill governance.

Do not call Skillcheck for ordinary coding, debugging, testing, writing,
repository exploration, or tasks that merely use an already-selected Skill.

For a relevant request, call skillcheck_analyze first. If no candidate groups are returned,
stop: Do not call skillcheck_evidence and do not save an empty
review. Otherwise read bounded evidence, explain the decision, and save only
when the user asked for a persisted review or confirmed a sync group.

You may propose KEEP_BOTH, MERGE, DEPRECATE, DELETE_DUPLICATE, RENAME,
REWRITE_BOUNDARY, or MANUAL_REVIEW.

Skillcheck performs deterministic local analysis and saves governance reports.
It never runs Codex, Claude, or another Agent subprocess, and it never edits,
deletes, renames, or installs the user's Skill files. Evidence page numbers are
zero-based; bodies are optional, redacted, and bounded.
""".strip()
