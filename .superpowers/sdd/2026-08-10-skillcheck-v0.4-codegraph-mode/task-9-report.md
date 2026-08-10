# Task 9 report — Agent integration installation

## Status

Completed.

- Added marker-fenced instruction management with compare-and-swap writes, idempotent replacement, malformed-marker refusal, and owned-block-only removal.
- Added global/project instruction paths and instruction status to Codex, Claude Code, and Cursor target detection.
- Added preview-first, multi-Agent `InstallPipeline` with atomic writes, validation, MCP stdio smoke-start check, cancellation, and rollback on write or validation failure.
- Added `skillcheck install` with `--target`, `--location`, `--yes`, and non-writing `--print-config`.

## Verification

```text
python -m pytest tests/targets tests/pipelines/test_install_pipeline.py tests/commands/test_install_command.py -q
23 passed

python -m ruff check <Task 9 paths>
All checks passed
```

## Commit

Pending commit: `feat: wire skillcheck into local agents`

## Concerns

- The smoke check starts `skillcheck serve --mcp` without a protocol request, verifies it remains alive briefly, and then terminates it. It intentionally does not invoke an Agent model.
- Persisting configured-target status in the v0.4 application configuration is owned by the CLI/status flow work in Task 10.
