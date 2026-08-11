# Task 12 Report — Remove legacy agent-review architecture

## Completed

- Removed the legacy reviewer adapters, direct LLM client, review pipeline, setup/compat commands, menu, migration code, v1/v2 storage layer, and their registrations.
- Removed the legacy service/store/discovery/report-builder layers that depended on the deleted review configuration and database migration stack.
- Reworked configuration into one strict, migration-free v4 document. `AppConfig` accepts only the v4 sections; non-v4 schemas and unsupported fields fail without modifying the source file.
- Moved v4 catalog, report, staging, MCP runtime, command, and test callers to the nested `catalog` and `reports` configuration sections.
- Removed the unused OpenAI dependency and old compatibility version output.
- Replaced legacy tests with an architecture guard and v4 configuration tests; adjusted surviving v4 tests to use the new configuration paths.

## Verification

- `python -m pytest tests/architecture/test_no_legacy_review.py tests/config/test_loader.py -q` — 4 passed.
- `python -m pytest -q` — 206 passed, 2 skipped.
- `python -m ruff check src tests` — passed.

## Note

The full test run emits one third-party Pydantic forward-reference warning from the MCP dependency. It does not affect the project test result.
