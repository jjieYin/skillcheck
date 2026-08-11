# Task 11: Connect source preflight to controlled installs

## Delivered

- Source analysis stages untrusted input, creates an expiring source preflight, and records only incoming-source deterministic blockers.
- `skillcheck add` now presents the preflight result and requires explicit confirmation unless `--yes` is supplied.
- Installation re-stages the source, verifies its hash, rejects expired or deterministically unsafe input, and only then writes to the chosen Agent target.

## Verification

- `python -m pytest tests/governance/test_source_preflight.py tests/pipelines/test_add_pipeline.py tests/commands/test_add.py tests/acceptance/test_v4_add_journey.py -v` — 11 passed
- `python -m ruff check` over the Task 11 production and test paths — passed
- `git diff --check` — passed

## Concerns

- Agent review status is informational: deterministic source safety findings and explicit confirmation remain the only installation gates, as specified.

## Review fixes

- The prepared hash must now equal the linked preflight hash; a source change between the first staging pass and analysis is rejected.
- Source preflight now uses the existing deterministic validator for every staged Skill, covering shell/process execution, credentials, hidden Unicode, remote-download pipes, and unsafe paths. Malformed Skill metadata is also blocked as `SEC006`.
- Local directory sources reject symlinks before their hash can be calculated or files copied during installation.
