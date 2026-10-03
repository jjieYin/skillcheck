# SDD ledger — plan: docs/superpowers/plans/2026-09-27-governance-algorithm-p0-p1.md

Setup: native worktree was created but the sandbox denied writes outside the workspace root; execution is continuing in the user-approved F:\skillcheck checkout. The detached worktree remains untouched.

Pre-flight: Task 1 produces GovernancePolicy and embedding_signature consumed by Tasks 2–3; Task 4 produces PairSignals consumed by Tasks 5 and 7; Task 6 produces instruction_hash and official fields consumed by Task 7; Task 8 consumes the root/path model from Tasks 3 and 6. No interface conflicts found against the spec.

Task 1: Ruling: `tests/commands/test_groups.py` remains a known environment baseline failure under the active Typer version (`Path | None` unsupported by the installed Typer); the algorithm task will not change unrelated CLI annotations. Task 1 verification uses the policy, config, MCP and governance suites that execute under the declared project API.

Task 1: complete (commit unavailable: sandbox denied `.git/index.lock`; tests: `PYTHONPATH=src pytest tests/governance/test_policy.py tests/config/test_loader.py tests/mcp/test_tools.py tests/governance/test_analyzer.py -q` → 31 passed; Ruff targeted check → All checks passed).

Task 2: complete (commit unavailable: sandbox denied `.git/index.lock`; current embedding signature is wired through MCP reconciliation and governance reads; missing current-model vectors are backfilled; `AUDIT002` reports inconsistent dimensions; tests: 66 passed across MCP, catalog, governance, and audit suites; Ruff targeted check → All checks passed).

Task 3: complete (commit unavailable: sandbox denied `.git/index.lock`; `AnalysisScope`/`ScopeSelector` now enforce all/global/project/custom, source analysis keeps staged Skills while filtering the catalog, and analyzer/pipeline APIs no longer expose `limit`; tests: `PYTHONPATH=src pytest tests/governance/test_selection.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/mcp -q` → 47 passed; broader selected regression → 89 passed, 4 known Typer-environment failures in CLI/acceptance tests due installed Typer rejecting `Path | None`; Ruff targeted check → All checks passed).

Task 4: complete (commit unavailable: sandbox denied `.git/index.lock`; added `PairSignals`, relation decisions no longer use Skill findings in the new API, conflict requires `conflict_similarity`, permission modes retain multiple read/write declarations, and structured `skill_findings` are persisted and rendered separately; tests: 60 passed across features, decisions, audit, governance, reports, reviews and MCP; Ruff targeted check → All checks passed).

Task 5: complete (commit unavailable: sandbox denied `.git/index.lock`; overlap/variant groups now require complete pair connectivity, conflicts remain binary, pair evidence and min/mean/max similarity are modeled, persisted in `evidence`, and returned through bounded evidence pages; tests: 29 passed across grouping, evidence, reviews, reports and audit; Ruff targeted check → All checks passed).

P0 Gate:定向回归通过（147 passed）；run parameters 现记录 `scope`、thresholds、embedding signature、security、skill findings；全量回归记录为 265 passed, 30 failed, 2 skipped，失败均为当前环境旧 Typer 对 `Path | None` 的既有 CLI/acceptance 兼容问题；`ruff check src tests` 通过。按计划暂停等待人工审阅，未开始 Task 6。

Task 6: complete (commit unavailable: sandbox denied `.git/index.lock`; Catalog v6 adds package/instruction double hashes and official frontmatter fields, migrates v5 atomically with conservative fallback, and reconciliation repairs fallback hashes without directory changes; tests: 43 catalog/parser tests plus the P0 selected regression → 151 passed; Ruff verification pending after P1 implementation).

Task 7: complete (commit unavailable: sandbox denied `.git/index.lock`; Unicode-aware activation/procedure features, CJK 2–4 grams, Latin unigram/bigrams, hash embedding revision, instruction/lexical/dense hybrid retrieval, capability Jaccard, and one source/library candidate path are implemented; tests: 47 candidate/features/embedding/audit/analyzer/source tests passed; Ruff passed).

Task 8: complete (commit unavailable: sandbox denied `.git/index.lock`; Catalog and staged source now share official FMT/QLT/SEC validation, safe text scans cover package files, and CompositeSkillValidator gates optional SkillSpector strictly by SecurityConfig with non-blocking sanitized CAP002 failures; tests: validator/security/analyzer/source suites passed; Ruff passed).

Task 9: complete (commit unavailable: sandbox denied `.git/index.lock`; MCP/report instructions and docs describe scope, hashes, findings, pair evidence and SkillSpector; reports persist pair evidence/statistics; acceptance journey covers isolated runtime, project filtering, current-vector refresh, Chinese overlap, chain non-merge, evidence and no file mutation; acceptance: 2 passed; final targeted governance regression: 174 passed, 2 skipped; full quality: 287 passed, 30 failed, 2 skipped, all 30 failures remain the known installed-Typer `pathlib.Path | None` CLI/acceptance incompatibility; added explicit evidence for identical instructions with differing package assets; `ruff check src tests` passed; `compileall` passed; `python -m build --no-isolation` unavailable because the environment has no `build` module).
