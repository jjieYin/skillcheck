# Task 3 report — scoped duplicate and mirror classification

## Delivered

- Added `GovernanceScopeKey`, with the specified normalized provider, scope,
  resolved project path, and root ID fields.
- Added `ScopeClassifier`, which first buckets snapshots by content hash and
  then classifies same-scope copies as `EXACT_DUPLICATE` and identical copies
  spanning two or more scope keys as `MIRRORED_COPY`.
- Added the exact `MIRRORED_COPY` and `SYNC_GROUP_DRIFT` relation values.
- Updated `GovernanceAnalyzer` to replace the core auditor's unscoped exact
  duplicate groups with scope-aware classifier output, preventing duplicate
  unscoped exact groups.
- Added coverage for normalized scope keys, same-root duplicates, cross-agent
  mirrors, non-identical cross-agent Skills, and analyzer integration.

## Verification

- RED: `test_scopes.py` initially failed because `skillcheck.governance.scopes`
  did not exist.
- PASS: scopes and analyzer tests — 17 passed.
- PASS: required governance set (`test_scopes.py`, `test_analyzer.py`, and
  `test_evidence.py`) — 21 passed.
- PASS: Ruff for changed code and tests.
- PASS: full suite — 230 passed, 2 skipped.

## Risk

Scope classification intentionally concerns only content-hash identity. Similar
but non-identical Skills from different agents remain available to the existing
semantic analyzer and are never automatically labelled as mirrors. The full
suite has one pre-existing third-party Pydantic incomplete-forward-reference
warning in `tests/mcp/test_contract.py`; it does not fail tests.
