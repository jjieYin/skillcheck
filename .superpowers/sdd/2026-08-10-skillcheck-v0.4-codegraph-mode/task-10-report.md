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

`fb8b372 feat: make CLI a bootstrap and fallback interface`
