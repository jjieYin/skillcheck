# Task 6 report: MCP save sync group

## Delivered

- Added the exact fourth MCP tool: `skillcheck_save_sync_group`.
- It accepts only current `MIRRORED_COPY` candidates from the supplied analysis run.
- The MCP facade validates the run/group relationship, complete unique member set, authority membership, `monitor_only` policy, and current run revision/snapshots before persisting through `SyncGroupService`.
- Stale analysis raises `StaleAnalysisError`; the flow stores monitor-only metadata and never copies or edits Skill files.
- `SyncGroupService.create()` now explicitly accepts and enforces the monitor-only policy.

## Verification

`PYTHONPATH=src C:\skillcheck-test-venv\Scripts\python.exe -m pytest tests/mcp -q --basetemp .test-tmp-all -p no:cacheprovider`

Result: **16 passed**. One pre-existing third-party Pydantic settings warning was emitted.

## Risk

The repository verifies the analyzed revision and snapshots immediately before creation; the service also atomically rechecks active current snapshots before it writes the group. There is no Skill-file write path in this feature.
