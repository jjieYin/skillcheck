# Task 2 report — monitor-only sync groups

## Delivered

- Added the `SyncPolicy`, `SyncMemberRole`, `SyncGroupStatus`, `SyncGroupMember`,
  and `SyncGroup` governance models.
- Added `SyncGroupService` for creating and removing monitor-only synchronization
  groups. Creation always records the authority Skill first and records every
  remaining member as a mirror.
- Added transactional sync-group repository operations:
  `insert_sync_group`, `get_sync_group`, `list_sync_groups`, and
  `delete_sync_group`.
- Exported the new public models and service from `skillcheck.governance`.

## Safety boundaries

- The only supported policy is exactly `monitor_only`.
- Creation requires at least two distinct members, including the authority.
- Every member must have a current, active Skill snapshot.
- Member baselines use the current snapshot ID and content hash, and the
  repository rechecks active status and snapshot identity inside the same
  `BEGIN IMMEDIATE` transaction that persists the group.
- A Skill can appear in only one group. The application validates this and the
  v5 schema's `UNIQUE(skill_id)` constraint is the final concurrency boundary.
- Removing a group deletes only the group and cascade-owned member records;
  it does not delete Skills or snapshots.

## Tests

- RED attempt: the initial shell environment had no `python` command. Running
  with the first discovered Python collected tests but lacked `pydantic`; no
  production code was executed through that environment. The provided bundled
  runtime was then used for verification.
- PASS: `PYTHONPATH=src <bundled-python> -m pytest
  tests/governance/test_sync_groups.py tests/governance/test_analyzer.py -q`
  — 15 passed.
- PASS: Ruff on all changed implementation and test files.
- PASS: `PYTHONPATH=src <bundled-python> -m pytest -q` — 225 passed, 2 skipped.

## Risks / notes

- Full suite has one pre-existing third-party Pydantic incomplete
  forward-reference warning in `tests/mcp/test_contract.py`; it does not fail
  the suite and is unrelated to sync groups.
- The mandatory Skillcheck analysis call could not complete because its remote
  approval stream disconnected. No Skill files were read or modified as part of
  this task.
