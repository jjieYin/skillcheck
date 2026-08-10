# Task 10 report — CLI bootstrap, status, and local scan

## Status

Completed.

- Added `skillcheck status`, with read-only text/JSON state for configured Agents, catalog initialization, root and Skill counts, revision, latest sync, watcher mode, pending count, and warnings.
- Replaced the old menu default with a bootstrap flow: an unconfigured installation shows the Agent integration guide; an already configured installation shows status and directs users to ask their Agent for governance work.
- Replaced `scan` with a local-only fallback that synchronizes the catalog, performs deterministic library analysis, and writes a local report. It accepts only an optional path, `--config`, and `--json`; it does not launch an Agent subprocess or run an Agent review.
- Kept one temporary `ReviewMode` import contract solely for the still-registered legacy `add` command. Task 11 rewrites `add`, and Task 12 removes this compatibility layer with the remaining legacy review architecture.

## Verification

```text
python -m pytest tests/app/test_main.py tests/commands/test_status.py tests/commands/test_scan.py tests/acceptance/test_v4_cli_journey.py -v
7 passed

python -m ruff check <Task 10 paths>
All checks passed

git diff --check
passed
```

## Commit

`64afdb3 feat: make CLI a bootstrap and fallback interface`

## Fix round 1

- Successful `skillcheck install` now writes the selected, validated Agents into `targets.configured`, together with the installed scope and validation status. The write runs only after all MCP/instruction validation and the smoke check pass.
- The install pipeline accepts an internal post-success callback. If the atomic configuration write fails, it rolls back the already written MCP/instruction files along with any other installation failure.
- `--print-config` and a cancelled install still leave configuration absent; the command does not create its config before confirmed application.
- Removed the obsolete `agent_reviews` field from the local scan result and its JSON output. The local fallback now exposes only local synchronization, analysis, and report artifacts.

```text
python -m pytest tests/commands/test_install_command.py tests/pipelines/test_install_pipeline.py tests/commands/test_scan.py tests/acceptance/test_v4_cli_journey.py tests/app/test_main.py tests/commands/test_status.py -v
18 passed

python -m ruff check <Task 9/10 fix paths>
All checks passed
```
