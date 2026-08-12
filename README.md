# Skillcheck

## Keep your local Skills useful as the library grows

Skillcheck is a local-first CLI and MCP server for discovering, indexing, and reviewing personal `SKILL.md` libraries.

It finds duplicate and overlapping Skills, gives your current Agent bounded evidence, and lets that Agent explain whether a Skill should be kept, merged, renamed, rewritten, deprecated, or reviewed manually.

**No second Agent. No automatic deletion. No hidden file changes.**

## Contents

- [Get started](#get-started)
- [The problem it solves](#the-problem-it-solves)
- [How it works](#how-it-works)
- [Use it from your Agent](#use-it-from-your-agent)
- [Use it from the CLI](#use-it-from-the-cli)
- [MCP tools](#mcp-tools)
- [What gets indexed](#what-gets-indexed)
- [Safety model](#safety-model)
- [Configuration and data](#configuration-and-data)
- [Upgrade and uninstall](#upgrade-and-uninstall)
- [Troubleshooting](#troubleshooting)
- [Supported platforms and Agents](#supported-platforms-and-agents)

## Get started

### 1. Install the CLI

The release contains self-contained executables. Python, Node.js, and a compiler are not required.

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.ps1 | iex
```

**macOS / Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.sh | sh
```

Open a new terminal if your shell does not see the command immediately:

```sh
skillcheck version
```

The installer verifies the release manifest and SHA-256 checksum before installing the executable.

### 2. Connect the Agents you use

```sh
skillcheck install
```

The installer detects Codex CLI, Claude Code, and Cursor, shows the files it will touch, and asks for confirmation. It adds the Skillcheck MCP entry and a small instruction block to the selected Agent.

This step connects the Agent. It does not delete, rewrite, or install your Skills.

The first interactive install preselects detected Agents. On later runs the
checkboxes show the exact selection saved last time: Space toggles a row and
Enter applies the final list. An unchecked Agent is removed from Skillcheck's
MCP entry and instruction block, while other user-owned configuration remains
untouched. `--yes` skips only the final confirmation; it never silently selects
all detected Agents. In a non-interactive terminal, pass an explicit
`--target`.

To select targets explicitly:

```sh
skillcheck install --target codex
skillcheck install --target claude,cursor
skillcheck install --target all
```

### 3. Build your personal Skill index

```sh
skillcheck init
```

Skillcheck discovers the standard local roots and recursively indexes every `SKILL.md` below them. You can add extra roots during initialization:

Every matching `SKILL.md` below every configured root is indexed, regardless of
nesting depth. Agent connection scope and Skill scan scope are independent: a
connected Agent does not limit which personal Skills are audited.

```sh
skillcheck init ~/my-skills ./team-skills
```

After initialization, ask your Agent directly:

```text
Check my local Skills for duplicates and overlapping boundaries.
For each candidate, recommend KEEP_BOTH, MERGE, DELETE_DUPLICATE,
RENAME, REWRITE_BOUNDARY, DEPRECATE, or MANUAL_REVIEW, and explain why.
```

## The problem it solves

A growing Skill library creates three different problems:

- **Exact copies:** the same Skill is installed in multiple locations.
- **Overlapping capabilities:** two Skills describe similar tasks but have different names or implementations.
- **Unclear boundaries:** a parent Skill, a variant, and a conflict can look similar from metadata alone.

Skillcheck separates these jobs:

```text
CLI          discovers, indexes, syncs, and performs confirmed writes
Rules        detect exact duplicates and rank deterministic candidates
MCP          returns bounded, redacted evidence to the connected Agent
Agent        makes the semantic governance decision
User         confirms any installation or file change
```

## How it works

### Local index

`skillcheck init` and the MCP runtime scan the configured roots recursively. A Skill is a directory containing a file named exactly:

```text
SKILL.md
```

The index stores the Skill name, description, body, tools, permissions, environments, inputs, outputs, source path, current status, and immutable content snapshots in a local SQLite database. A full-text index supports local lookup.

### Incremental sync

When the MCP server connects, it reconciles file metadata and content hashes before answering the first query. During an Agent session, file changes enter a debounced watcher and only affected Skills are re-indexed. `skillcheck sync` remains available for scripts, disabled watchers, and explicit maintenance.

### Duplicate and overlap analysis

Skillcheck uses layered, explainable analysis:

1. **Content hash:** identical canonical content is classified as `EXACT_DUPLICATE`.
2. **Vector similarity:** names, descriptions, capability fields, and bodies are encoded and compared with cosine similarity.
3. **Rules:** similarity, permissions, environments, and quality findings produce candidate relations such as `HIGH_OVERLAP_CANDIDATE`, `VARIANT_CANDIDATE`, `CONFLICT_CANDIDATE`, `QUALITY_ISSUE`, and `SECURITY_ISSUE`.

The base installation works offline with a deterministic feature-hash embedding. An optional local sentence-transformer backend can be configured for stronger semantic retrieval.

These steps produce candidates and evidence. They do not decide that a file must be deleted.

Library analysis is complete by default. MCP `skillcheck_analyze` does not take
a hidden top-N limit; evidence pagination limits only how much evidence is
returned per page, not how many Skills are analyzed. Direct library APIs may
still accept an explicit limit for compatibility with scripts.

### Agent review

The connected Agent reads the candidate evidence and applies its own model to the actual Skill boundaries. It can distinguish a true duplicate from a reasonable environment-specific variant, then save a review with a reason, confidence, and recommendations.

## Use it from your Agent

Once `install` and `init` are complete, the normal interface is natural language in Codex, Claude Code, or Cursor:

```text
Review the Skills in my personal library.
Group exact duplicates separately from semantic overlaps.
Do not change any files; just produce recommendations.
```

For an incoming Skill before installation:

```text
Review this Skill source before I install it.
Compare it with my existing library and call out duplicates,
permission conflicts, security blockers, and boundary changes.
```

The Agent uses the local MCP server. Skillcheck does not start a Codex, Claude, or other Agent subprocess.

Skillcheck is intentionally conditional. It is used for local Skill inventory,
duplicates, overlap, conflicts, installation preflight, cross-Agent mirrors,
sync groups, or governance. Ordinary coding, debugging, testing, writing,
repository exploration, and tasks that merely use an already-selected Skill do
not call Skillcheck.

## Use it from the CLI

### Scan the existing library without an Agent

```sh
skillcheck scan
```

`scan` synchronizes the catalog, runs the complete deterministic local audit, and writes Markdown and JSON reports. It is the fallback when no Agent is configured or when you want a repeatable terminal check.

View the newest report:

```sh
skillcheck report latest
```

Machine-readable output:

```sh
skillcheck scan --json
```

### Add a local directory, ZIP, or GitHub source

```sh
skillcheck add ./new-skill
skillcheck add ./skills.zip --target codex
skillcheck add https://github.com/owner/repository --target claude
```

`add` stages the source, checks its structure and deterministic blockers, shows the source hash and target paths, and waits for confirmation. Only the confirmed CLI write installs the files.

### Inspect and maintain the installation

```sh
skillcheck status
skillcheck status --json
skillcheck sync
skillcheck doctor
skillcheck upgrade
skillcheck uninstall
```

`doctor` is read-only by default. `uninstall` removes Skillcheck's own MCP and instruction markers; it does not remove your user Skills.

### Start the MCP server manually

This is normally started by the Agent configuration:

```sh
skillcheck serve --mcp
```

The server uses MCP stdio. It does not open a network port or run as a permanent background daemon.

## MCP tools

Skillcheck exposes four Agent-facing tools:

| Tool | Purpose | Returns |
| --- | --- | --- |
| `skillcheck_analyze` | Analyze the current library or an incoming source | `run_id`, summary, candidate groups, deterministic findings, sync state |
| `skillcheck_evidence` | Read one candidate group page by page | Redacted metadata, body excerpts when requested, shared/different capabilities, stale state |
| `skillcheck_save_review` | Save the Agent's explicit governance decision | Review ID, decisions, confidence, Markdown path, JSON path |
| `skillcheck_save_sync_group` | Save a user-confirmed monitor-only cross-Agent mirror group | Group ID, authority, members, baseline status |

The intended sequence is:

```text
skillcheck_analyze
        ↓
skillcheck_evidence
        ↓
Agent semantic decision
        ↓
skillcheck_save_review
```

Review writes are rejected when the run, group, schema, or content snapshot is invalid or stale.

`MIRRORED_COPY` means the same Skill is intentionally present in different
Agent scopes; it is not counted as local redundancy. A sync group records the
chosen authority and immutable member baseline for monitoring only. It never
automatically copies, overwrites, deletes, or renames a Skill.

## What gets indexed

By default, Skillcheck checks these roots when they exist:

| Agent / source | Global root | Project root |
| --- | --- | --- |
| Codex | `~/.codex/skills` | `.codex/skills` |
| Claude Code | `~/.claude/skills` | `.claude/skills` |
| Shared Agent Skills | `~/.agents/skills` | `.agents/skills` |
| Cursor | `~/.cursor/rules` | `.cursor/rules` |

Every nested directory is eligible. A directory is not indexed merely because it has a README; it must contain a readable `SKILL.md`.

## Safety model

- The MCP server is read-only with respect to Skill files.
- Analysis never launches another Agent subprocess.
- Evidence is bounded and redacted before it is returned to the Agent.
- `scan` produces recommendations; it does not edit or delete Skills.
- `add` requires an explicit confirmation before writing to an Agent target.
- Install and uninstall only modify Skillcheck-owned integration markers and files.
- Content hashes and snapshots make reports traceable to the exact indexed version.

## Configuration and data

The default local state directory is:

```text
Windows:  %USERPROFILE%\.skillcheck
macOS:    ~/.skillcheck
Linux:    ~/.skillcheck
```

It contains the configuration, SQLite catalog, reports, and temporary staging data. Set `SKILLCHECK_HOME` to use an isolated test or backup location:

```powershell
$env:SKILLCHECK_HOME = "$env:TEMP\skillcheck-test"
```

The core scan is local. Network access is only needed when you explicitly install or upgrade from a remote source.

## Upgrade and uninstall

Upgrade the installed executable:

```sh
skillcheck upgrade
```

Or rerun the platform installer to fetch the latest verified release.

Remove the integration while keeping your Skills:

```sh
skillcheck uninstall
```

Use the command's confirmation prompt to review the exact files before removal.

## Troubleshooting

### `Skill: 0`

Check whether the configured roots actually contain `SKILL.md` files:

```powershell
Get-ChildItem "$HOME\.codex\skills", "$HOME\.claude\skills", "$HOME\.agents\skills", "$HOME\.cursor\rules" -Recurse -Filter SKILL.md -ErrorAction SilentlyContinue
```

Then refresh the catalog:

```sh
skillcheck sync
skillcheck status
```

### Some files are `invalid`

The file was found, but it could not be read or its YAML front matter was invalid. Run:

```sh
skillcheck scan --json
skillcheck report latest
```

### The Agent cannot see Skillcheck

Check the integration and MCP handshake:

```sh
skillcheck doctor
skillcheck install
```

Restart the Agent after changing its MCP configuration.

## Supported platforms and Agents

### Platforms

- Windows x64
- Linux x64
- macOS Intel
- macOS Apple Silicon

### Agents

- Codex CLI
- Claude Code
- Cursor

## License

MIT. See [LICENSE](LICENSE).
