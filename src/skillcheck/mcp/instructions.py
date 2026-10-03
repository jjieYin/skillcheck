"""Instructions exposed to connected Agents."""

MCP_INSTRUCTIONS = """
Only use Skillcheck when the user's request concerns local Skill inventory,
duplication, overlap, conflicts, installation preflight, cross-Agent mirrors,
sync groups, or Skill governance.

Do not call Skillcheck for ordinary coding, debugging, testing, writing,
repository exploration, or tasks that merely use an already-selected Skill.

Every skillcheck_analyze call analyzes the complete indexed library or complete validated
incoming source. Do not use a Skill-count limit; top_k only controls neighbors per
retrieval channel. Evidence remains redacted and paginated. Findings attached to one
Skill are independent from pair relationship groups.
The scope argument accepts only all, global, project, or custom. Project scope requires
the current runtime project path; source analysis always includes the staged source and
uses scope only for the local catalog comparison set.
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
Catalog records retain both a package content_hash (SKILL.md plus safe assets) and
an instruction_hash (semantic frontmatter plus normalized SKILL.md instructions).
Pair evidence includes the dense/lexical/capability signals and min/mean/max
similarity statistics. Built-in format, quality, and security checks always run;
SkillSpector is optional and runs only when explicitly enabled with a configured
command. Deterministic analysis proposes candidates; the current Agent remains
the semantic final reviewer.
""".strip()
