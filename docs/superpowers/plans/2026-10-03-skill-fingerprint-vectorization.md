# Skill 指纹、分段表示与可插拔向量化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持默认离线运行和现有 MCP/写入安全边界的前提下，用分层指纹、分段多通道证据和可插拔向量化接口替换当前单一 `instruction_hash`/单向量/`max()` 判定链路。

**Architecture:** 解析阶段生成 `package_hash`（数据库继续叫 `content_hash`）、`behavior_hash` 和 `execution_hash`；正文被确定性切分为 activation、procedure、constraint 三类通道。向量化通过注册表提供 Hash 与可选本地 SentenceTransformer 适配器，分段向量以模型签名隔离存储。候选召回合并指纹、带 IDF 的词法、能力和可选语义通道，关系判定使用 `PairSignalsV2` 的门控条件和关系专属分数，不再把不同信号取 `max()` 后解释为统一语义分数。

**Tech Stack:** Python 3.11+, Pydantic 2, SQLite, NumPy, PyYAML, pytest；`sentence-transformers` 仅作为 `local-embedding` 可选依赖。

**Spec:** `docs/superpowers/specs/2026-10-03-skill-fingerprint-segmented-representation-design.md`

## Global Constraints

- 默认安装继续离线、轻量，不强制安装外部 embedding 或 reranker。
- `package_hash` 延续现有 `content_hash` 的完整安全文件语义；数据库列不重命名，并提供只读 `package_hash` 属性。
- `behavior_hash` 只包含声明行为字段和规范化正文；不包含 `name`、`id`、`license`、任意 `metadata`、assets、references、scripts 内容。
- `execution_hash` 只扫描 `scripts/**` 安全普通文件；无 scripts 使用带版本的固定空指纹，读取失败使用 `null`，两者不得混淆。
- 固定空执行指纹不得作为独立候选召回键。
- 普通 chunk 最大 800 个 Unicode 字符；超长段落按 800 字符切分并保留 100 字符重叠；代码块单独成块。
- 只使用确定性中英文约束词表；词表命中只产生结构化证据，不直接判定冲突。
- 词法通道使用分析范围即时 IDF：`idf(feature) = log((N + 1) / (df(feature) + 1)) + 1`；单个 chunk 词频上限为 3。
- `HashVectorizationBackend` 的类型是 `lexical_hash`，不得把其结果写入 `semantic_similarity`。
- 配置只能选择 registry 中已注册 backend，不允许从配置字符串动态导入 Python 模块。
- 空文本不提交给模型；批量编码必须检查行数、维度、有限数值和归一化声明，任一失败整批拒绝写入。
- 新向量签名至少为 `<backend>:<model-id>:<model-revision>:d<dimensions>:<kind>:section-<revision>:feature-<revision>`；签名不同不得混用向量或阈值。
- 未配置并校准 `threshold_profile` 的语义模型只能参与候选召回，不得驱动自动高重叠关系。
- Catalog v6→v7 只增加可空指纹列和 `segment_vectors` 结构；迁移/回填失败必须回滚，不使用旧哈希伪造 v2 指纹。
- 保留 `skillcheck_analyze`、`skillcheck_evidence`、`skillcheck_save_review`、`skillcheck_save_sync_group` 的名称、确认语义、分页、脱敏和 `MIRRORED_COPY=monitor_only` 边界。
- 不训练自有模型，不实现具体远程 embedding 供应商，不自动删除/合并/改写/安装 Skill，不启动第二个 Agent。
- 实现顺序固定为：回归 fixtures → 分层指纹/Catalog v7 → sections/约束/IDF → 多通道向量与候选 → 关系/证据/报告 → 标注集门禁。

## Review Focus

- 纯 metadata 或排版变化是否错误改变行为关系；由 Task 1/2 的 `metadata_only`、`format_only` 回归测试固定。
- `scripts` 读取失败是否被误认为“没有脚本”；由 Task 2 的不可读脚本测试固定。
- 共享公共模板是否把无关 Skill 推成高重叠；由 Task 3/6 的 shared-boilerplate 困难负样本固定。
- `ALWAYS` 与 `NEVER` 同动作是否只得到高相似度而丢失极性；由 Task 3/6 的 polarity mismatch 测试固定。
- 可选向量模型缺失、NaN、维度不一致或签名变化是否污染现有索引；由 Task 4/5 的降级、批次拒绝和签名隔离测试固定。

### Task 1: 固化可移植回归 fixtures 与评估接口

**Files:**
- Create: `tests/fixtures/fingerprints/exact-copy/SKILL.md`
- Create: `tests/fixtures/fingerprints/metadata-only/SKILL.md`
- Create: `tests/fixtures/fingerprints/format-only/SKILL.md`
- Create: `tests/fixtures/fingerprints/asset-only/SKILL.md`
- Create: `tests/fixtures/fingerprints/asset-only/assets/example.txt`
- Create: `tests/fixtures/fingerprints/script-only/SKILL.md`
- Create: `tests/fixtures/fingerprints/script-only/scripts/check.py`
- Create: `tests/fixtures/fingerprints/polarity-required/SKILL.md`
- Create: `tests/fixtures/fingerprints/polarity-forbidden/SKILL.md`
- Create: `tests/fixtures/fingerprints/full/SKILL.md`
- Create: `tests/fixtures/fingerprints/lite/SKILL.md`
- Create: `tests/fixtures/fingerprints/unrelated-a/SKILL.md`
- Create: `tests/fixtures/fingerprints/unrelated-b/SKILL.md`
- Create: `tests/fixtures/fingerprints/shared-boilerplate-a/SKILL.md`
- Create: `tests/fixtures/fingerprints/shared-boilerplate-b/SKILL.md`
- Create: `tests/fixtures/fingerprints/cjk/SKILL.md`
- Create: `tests/fixtures/fingerprints/mixed-language/SKILL.md`
- Create: `tests/helpers_fingerprints.py`
- Create: `tests/acceptance/test_fingerprint_regression.py`
- Create: `tests/acceptance/test_vectorization_regression.py`

**Interfaces:**
- `tests.helpers_fingerprints.fixture_root(name: str) -> Path` returns a repository-relative fixture without reading a user-local Skill path.
- `tests.helpers_fingerprints.load_pair(name: str) -> tuple[Path, Path]` maps each named case to the two roots used by the tests.
- Later tasks consume the fixture names and expected invariants, not generated hashes.

- [ ] **Step 1: Add the fixture packages and keep their content minimal.**

  Encode only the behavior needed by the case: metadata-only changes `metadata`/author/version; format-only changes line endings/trailing whitespace; asset-only adds a file outside `SKILL.md`; script-only changes `scripts/check.py`; polarity pairs use the same action with `must/always` versus `must not/never`; full/lite share activation but have asymmetric procedures; boilerplate pairs share headings and generic instructions while their action nouns differ.

- [ ] **Step 2: Write the failing regression tests.**

  Add named tests for the 11 deterministic invariants in the spec: exact copy, metadata-only, format-only, asset-only, script-only, polarity mismatch, shared boilerplate, full/lite bidirectional coverage, CJK/mixed-language extraction, fake backend input order, and missing optional model fallback.

- [ ] **Step 3: Run the new tests before implementation.**

  Run: `python -m pytest tests/acceptance/test_fingerprint_regression.py tests/acceptance/test_vectorization_regression.py -q`

  Expected: FAIL because the v2 fingerprint, sections, vectorizer and PairSignalsV2 interfaces do not exist yet.

- [ ] **Step 4: Add a small evaluation result type without production dependencies.**

  In `tests/helpers_fingerprints.py`, expose `CaseResult(case, expected, actual, passed)` and a `run_case(...)` helper so later threshold experiments can report per-relation Precision/Recall without changing the catalog.

- [ ] **Step 5: Commit the fixtures and red tests.**

  ```bash
  git add tests/fixtures/fingerprints tests/helpers_fingerprints.py tests/acceptance/test_fingerprint_regression.py tests/acceptance/test_vectorization_regression.py
  git commit -m "test: add portable fingerprint and vectorization regression fixtures"
  ```

### Task 2: Implement layered fingerprints and Catalog v7 persistence

**Files:**
- Create: `src/skillcheck/core/fingerprints.py`
- Modify: `src/skillcheck/core/parser.py: canonical_skill_bytes, content_hash, instruction_hash, parse_skill`
- Modify: `src/skillcheck/models/skill.py: SkillRecord`
- Modify: `src/skillcheck/catalog/models.py: SkillSnapshot`
- Modify: `src/skillcheck/catalog/schema.sql: schema version, skill_snapshots, segment_vectors`
- Modify: `src/skillcheck/catalog/migrations.py: add V6_TO_V7_SQL`
- Modify: `src/skillcheck/catalog/database.py: schema_version_number, initialize, migration checks, expected tables/columns/indexes`
- Modify: `src/skillcheck/catalog/ids.py: snapshot identity documentation/tests only; do not change the existing package identity formula`
- Modify: `src/skillcheck/catalog/repository.py: snapshot persistence and segment vector records`
- Modify: `src/skillcheck/catalog/reconcile.py: parse/upsert/fingerprint lifecycle`
- Modify: `src/skillcheck/governance/analyzer.py: source snapshot construction`
- Test: `tests/test_parser.py`
- Test: `tests/catalog/test_models.py`
- Test: `tests/catalog/test_schema.py`
- Test: `tests/catalog/test_migrations.py`
- Test: `tests/catalog/test_repository.py`
- Test: `tests/catalog/test_reconcile.py`

**Interfaces:**
- `src/skillcheck/core/fingerprints.py`: `HASH_ALGORITHM_REVISION = "2"`, `EMPTY_EXECUTION_HASH = "sha256-v2:empty-scripts"`, `FingerprintResult(package_hash: str, behavior_hash: str, execution_hash: str | None, hash_algorithm_revision: str)`, and `FingerprintBuilder.build(root: Path, metadata: Mapping[str, Any], body: str) -> FingerprintResult`.
- `SkillRecord` and `SkillSnapshot` add `behavior_hash: str = ""`, `execution_hash: str | None = None`, and `hash_algorithm_revision: str = "2"`; `package_hash` is a read-only property returning existing `content_hash`.
- `CatalogRepository` adds `SegmentVectorRecord` plus `replace_segment_vectors(snapshot_id, model_signature, backend_kind, rows)` and `get_segment_vectors(snapshot_ids, model_signature)`; the old `save_vector/get_vectors` API remains for historical v1 vectors.
- `skill_snapshots` gains nullable `behavior_hash`, `execution_hash`, `hash_algorithm_revision`; `segment_vectors` uses the exact primary key `(snapshot_id, model_signature, channel, chunk_index)` and index from the spec.

- [ ] **Step 1: Write failing parser and model tests.**

  Assert that package hash still changes for any safe file, metadata-only changes leave `behavior_hash` unchanged, asset-only changes leave behavior/execution unchanged, script-only changes change `execution_hash`, no scripts use `EMPTY_EXECUTION_HASH`, and a script read error produces `execution_hash is None`.

- [ ] **Step 2: Implement `FingerprintBuilder` and refactor parser hashing.**

  Reuse the current safe-file traversal for `package_hash`; canonicalize behavior YAML mappings with stable keys, deduplicate/sort set-like fields, preserve body order/negation/code/parameters with LF and one final newline; scan only safe regular files under `scripts/**` for execution bytes. Keep `content_hash()` and `instruction_hash()` callable for compatibility and make `parse_skill()` populate all v2 fields.

- [ ] **Step 3: Add failing v6→v7 migration and repository tests.**

  Test schema version 7, new columns/table/index, atomic rollback on invalid v7 SQL, preservation of v6 columns/rows, nullable v2 fields for old snapshots, transactional replacement of all channels for one snapshot/signature, text hash persistence, and rejection of partial or malformed segment batches.

- [ ] **Step 4: Implement the v7 schema and migration.**

  Add `V6_TO_V7_SQL` with only `ALTER TABLE ... ADD COLUMN` and `CREATE TABLE/INDEX segment_vectors` statements, update validation helpers for v7, and preserve v4/v5 migration tests. Do not backfill v2 values from `content_hash`; leave them null until reconciliation computes real values.

- [ ] **Step 5: Thread fingerprints through snapshot upserts and source staging.**

  Extend `CatalogRepository.upsert_snapshot`, `CatalogReconciler._upsert_snapshot`, `_snapshot_from_row`, and `GovernanceAnalyzer._source_snapshots` with the three v2 fields. Reconcile must retain null fields and emit a non-blocking finding when the current file is unavailable instead of manufacturing equality.

- [ ] **Step 6: Run focused persistence tests and commit.**

  Run: `python -m pytest tests/test_parser.py tests/catalog/test_models.py tests/catalog/test_schema.py tests/catalog/test_migrations.py tests/catalog/test_repository.py tests/catalog/test_reconcile.py -q`

  Expected: PASS, with pre-existing full-suite dependency issues reported separately if encountered.

  ```bash
  git add src/skillcheck/core/fingerprints.py src/skillcheck/core/parser.py src/skillcheck/models/skill.py src/skillcheck/catalog/models.py src/skillcheck/catalog/schema.sql src/skillcheck/catalog/migrations.py src/skillcheck/catalog/database.py src/skillcheck/catalog/repository.py src/skillcheck/catalog/reconcile.py src/skillcheck/governance/analyzer.py tests/test_parser.py tests/catalog
  git commit -m "feat: add layered skill fingerprints and catalog v7"
  ```

### Task 3: Add deterministic SkillSections, constraint polarity and IDF lexical features

**Files:**
- Create: `src/skillcheck/core/sections.py`
- Modify: `src/skillcheck/core/features.py: activation_text, procedure_text, lexical_features, PairSignals compatibility`
- Modify: `src/skillcheck/config/models.py: channel/threshold profile fields if needed by deterministic extraction`
- Test: `tests/core/test_features.py`
- Create: `tests/core/test_sections.py`

**Interfaces:**
- `EmbeddingChannel = Literal["activation", "procedure", "constraint"]`.
- `ConstraintClause(text: str, polarity: Literal["required", "forbidden", "allowed", "conditional"], action_features: tuple[str, ...])`.
- `SkillSections(activation_text: str, procedure_chunks: tuple[str, ...], constraint_clauses: tuple[ConstraintClause, ...], capability_tokens: tuple[str, ...])`.
- `extract_skill_sections(skill: SkillRecord) -> SkillSections` is deterministic and side-effect free.
- `PairSignalsV2` replaces the current dataclass implementation while exporting `PairSignals = PairSignalsV2` as a compatibility alias; it keeps all old fields and adds the exact v2 fields from the spec, plus optional `relation_score` for relation-specific evidence.
- `idf_weights(feature_documents: Iterable[Counter[str]]) -> dict[str, float]` and `weighted_counter_cosine(left, right, idf) -> float` are pure helpers used by candidate retrieval.

- [ ] **Step 1: Write failing section/polarity tests.**

  Assert activation includes description and declared capability fields without synthetic labels; Markdown headings/lists/paragraphs/code blocks become ordered chunks; long text uses 800-character chunks with 100-character overlap; code blocks remain independent; required/forbidden/allowed/conditional words are classified in Chinese and English; action features are extracted independently of polarity; capabilities are field-qualified and stable.

- [ ] **Step 2: Implement `SkillSections` extraction.**

  Parse Markdown line-by-line without an LLM, preserve section order, normalize Unicode/whitespace, cap chunks as specified, and use the fixed bilingual polarity lexicon. Do not let a generic phrase match alone create a conflict.

- [ ] **Step 3: Write failing IDF and boilerplate tests.**

  Build a tiny corpus where a repeated heading/template receives lower weight than a rare action phrase, cap repeated feature counts at 3, calculate channel-local weights, and prove the shared-boilerplate pair is not recalled as high overlap solely by the template.

- [ ] **Step 4: Implement channel-local IDF helpers and PairSignalsV2.**

  Keep current CJK 2–4 grams and Latin unigram/bigram extraction, add the specified IDF formula and frequency cap, and add v2 fields: package/behavior/execution flags, activation lexical, bidirectional procedure coverage, constraint action similarity, polarity mismatch, hashed lexical, activation/procedure dense fields, capability similarity, permission difference and environment variant. `semantic_similarity` remains `None` for lexical-hash-only analysis.

- [ ] **Step 5: Run unit tests and commit.**

  Run: `python -m pytest tests/core/test_features.py tests/core/test_sections.py -q`

  ```bash
  git add src/skillcheck/core/sections.py src/skillcheck/core/features.py src/skillcheck/config/models.py tests/core/test_features.py tests/core/test_sections.py
  git commit -m "feat: add segmented skill sections polarity and IDF features"
  ```

### Task 4: Introduce the registry-based vectorization interface and configuration isolation

**Files:**
- Modify: `src/skillcheck/embeddings.py: replace whole-text protocol with channel-aware adapters while retaining compatibility aliases`
- Modify: `src/skillcheck/config/models.py: EmbeddingConfig, PrivacyConfig`
- Modify: `src/skillcheck/governance/policy.py: embedding_signature and GovernancePolicy`
- Modify: `src/skillcheck/app/context.py: backend construction and degraded capability state`
- Modify: `src/skillcheck/pipelines/init_pipeline.py: vectorizer wiring`
- Modify: `src/skillcheck/commands/sync.py: vectorizer wiring`
- Modify: `src/skillcheck/mcp/runtime.py: configured vectorizer wiring`
- Modify: `pyproject.toml: keep sentence-transformers optional; do not add it to base dependencies`
- Test: `tests/test_embeddings.py`
- Test: `tests/config/test_loader.py`
- Test: `tests/governance/test_policy.py`
- Test: `tests/mcp/test_runtime.py`

**Interfaces:**
- `VectorizerDescriptor(backend, model_id, revision, dimensions, kind, locality, normalized)` with `kind: Literal["lexical_hash", "semantic"]` and `locality: Literal["local", "remote"]`.
- `VectorizationInput(key: str, channel: EmbeddingChannel, text: str)`.
- `VectorizationBackend` protocol: `descriptor: VectorizerDescriptor` and `encode(inputs: Sequence[VectorizationInput]) -> np.ndarray`.
- `validate_vector_batch(inputs, values, descriptor) -> np.ndarray` rejects wrong row count/dimensions, NaN/Infinity, empty rows, and invalid normalization declarations before persistence.
- `VectorizationRegistry.register(name, factory)` and `backend_from_config(config) -> VectorizationBackend` instantiate only built-in registered factories; `FakeVectorizationBackend` is test-only and not registry-enabled in production.
- Built-ins are `HashVectorizationBackend`, `SentenceTransformerVectorizationBackend`; export `HashEmbeddingBackend` and `SentenceTransformerBackend` aliases for existing callers/tests.
- `EmbeddingConfig` retains `backend`, `model_id`, `dimensions`, `algorithm_revision`, `local_model`; adds optional `device`, positive `batch_size`, `threshold_profile`.
- `PrivacyConfig` adds `allow_remote_vectorization: bool = False`; no remote implementation is registered in this release.
- `embedding_signature(config, descriptor=None) -> str` emits the full backend/model/revision/dimensions/kind/section/feature signature; `GovernancePolicy` records signature, descriptor, threshold profile and whether semantic thresholds are calibrated.

- [ ] **Step 1: Write failing adapter contract tests.**

  Use the fake backend to assert input order/key/channel preservation; reject wrong rows, wrong dimensions, NaN/Infinity and invalid normalization; assert hash descriptor is `lexical_hash`, SentenceTransformer descriptor is `semantic`, optional import failure raises sanitized `EmbeddingUnavailable`, unknown backend names cannot import arbitrary modules, and the full signature changes when model, dimensions, section revision or feature revision changes.

- [ ] **Step 2: Implement descriptors, registry, validator and built-in adapters.**

  Make hash encoding operate on the supplied channel inputs and retain deterministic normalization. Make SentenceTransformer encode batches with `normalize_embeddings=True`, `device` and `batch_size`; catch all model-load/encode errors as `EmbeddingUnavailable` without Skill body or secret text in the message. Add a compatibility `encode_texts()` helper only where legacy tests need it; business code must use `VectorizationInput`.

- [ ] **Step 3: Implement config and policy validation.**

  Use Pydantic constraints for positive batch size, preserve old config files unchanged, default to local hash, include `section-1` and `feature-2` revisions in signatures, and require `allow_remote_vectorization` plus explicit opt-in before any future remote adapter could be selected. A missing threshold profile marks semantic results as retrieval-only.

- [ ] **Step 4: Implement offline fallback reporting.**

  When a requested optional local model cannot load, keep a hash vectorizer active and carry a `vectorizer_degraded` reason into the analyzer’s non-blocking findings; do not silently present the fallback as a semantic model.

- [ ] **Step 5: Run adapter/config tests and commit.**

  Run: `python -m pytest tests/test_embeddings.py tests/config/test_loader.py tests/governance/test_policy.py tests/mcp/test_runtime.py -q`

  ```bash
  git add src/skillcheck/embeddings.py src/skillcheck/config/models.py src/skillcheck/governance/policy.py src/skillcheck/app/context.py src/skillcheck/pipelines/init_pipeline.py src/skillcheck/commands/sync.py src/skillcheck/mcp/runtime.py pyproject.toml tests/test_embeddings.py tests/config/test_loader.py tests/governance/test_policy.py tests/mcp/test_runtime.py
  git commit -m "feat: add registry-based channel vectorization backends"
  ```

### Task 5: Persist and load channel vectors transactionally

**Files:**
- Create: `src/skillcheck/vectorization.py`
- Modify: `src/skillcheck/catalog/repository.py: SegmentVectorRecord, replace/get helpers`
- Modify: `src/skillcheck/catalog/reconcile.py: section extraction, batch encoding and transactional segment replacement`
- Modify: `src/skillcheck/governance/analyzer.py: source segment indexing and current-signature loading`
- Modify: `src/skillcheck/governance/analyzer.py: AUDIT002/AUDIT003 vector capability findings`
- Test: `tests/catalog/test_reconcile.py`
- Test: `tests/catalog/test_repository.py`
- Test: `tests/governance/test_analyzer.py`
- Test: `tests/acceptance/test_vectorization_regression.py`

**Interfaces:**
- `ChannelVectors(descriptor: VectorizerDescriptor, values: Mapping[str, Mapping[EmbeddingChannel, tuple[np.ndarray, ...]]])`.
- `VectorizationService.build_inputs(record: SkillRecord, sections: SkillSections) -> tuple[VectorizationInput, ...]` skips empty text and assigns deterministic `key` and per-channel `chunk_index` order.
- `VectorizationService.encode_record(record, sections) -> ChannelVectors` validates the complete batch before returning.
- `VectorizationService.replace_snapshot(snapshot_id, sections, encoded) -> None` replaces every channel for one `(snapshot_id, model_signature)` in one transaction; a failed batch leaves the previous complete set untouched.
- `CatalogRepository.get_segment_vectors(snapshot_ids, model_signature) -> dict[str, dict[EmbeddingChannel, tuple[np.ndarray, ...]]]` reads only the requested signature and validates stored dimensions/text hashes before returning.

- [ ] **Step 1: Write failing transactional vector tests.**

  Assert activation and multiple procedure chunks coexist, constraint chunks have their own channel, `text_hash` is stored, a second run with the same signature replaces all old chunks, a changed signature cannot read old chunks, wrong batch output leaves no partial rows, and model-unavailable fallback still completes lexical analysis.

- [ ] **Step 2: Implement `VectorizationService` and repository segment APIs.**

  Use `sha256` text hashes for each input, assign `chunk_index` separately per channel, call the public batch validator once per encoded batch, and perform delete/insert under `BEGIN IMMEDIATE` with rollback on any error. Keep the legacy `vectors` table untouched for historical reads.

- [ ] **Step 3: Integrate catalog reconciliation.**

  For active snapshots, extract sections after parsing, encode with the configured backend, replace current-signature segments, and preserve old vectors only as a compatibility artifact. If sections fail, retain activation/raw evidence and emit a non-blocking finding; if the optional model fails, use hash channels and mark the capability degradation.

- [ ] **Step 4: Integrate staged-source analysis.**

  Ensure `_source_snapshots` carries v2 fingerprints and that source records get in-memory `ChannelVectors` through the same service; source analysis must not depend on a user-local pre-existing vector row.

- [ ] **Step 5: Run persistence/integration tests and commit.**

  Run: `python -m pytest tests/catalog/test_reconcile.py tests/catalog/test_repository.py tests/governance/test_analyzer.py tests/acceptance/test_vectorization_regression.py -q`

  ```bash
  git add src/skillcheck/vectorization.py src/skillcheck/catalog/repository.py src/skillcheck/catalog/reconcile.py src/skillcheck/governance/analyzer.py src/skillcheck/core/validation.py src/skillcheck/core/validators.py tests/catalog tests/governance/test_analyzer.py tests/acceptance/test_vectorization_regression.py
  git commit -m "feat: persist segmented vectors by model signature"
  ```

### Task 6: Replace single-score retrieval and decisions with multi-channel PairSignalsV2

**Files:**
- Modify: `src/skillcheck/core/candidates.py: introduce MultiChannelCandidateRetriever and retain HybridCandidateRetriever compatibility wrapper`
- Modify: `src/skillcheck/core/retrieval.py: channel-aware cosine helpers and stable top-k ordering`
- Modify: `src/skillcheck/core/decisions.py: relation gates and relation-specific scores`
- Modify: `src/skillcheck/core/audit.py: v2 candidate source, exact/behavior groups and clique rules`
- Modify: `src/skillcheck/models/audit.py: PairEvidence v2 signal compatibility and relation score`
- Modify: `src/skillcheck/models/common.py: preserve legacy Decision values and add only required compatibility mappings`
- Modify: `src/skillcheck/governance/models.py: new candidate relation values and summary counters`
- Modify: `src/skillcheck/governance/analyzer.py: pass sections/channel vectors and record descriptor/profile`
- Test: `tests/core/test_candidates.py`
- Test: `tests/test_decisions.py`
- Test: `tests/test_audit.py`
- Test: `tests/governance/test_analyzer.py`
- Test: `tests/governance/test_grouping.py`

**Interfaces:**
- `MultiChannelCandidateRetriever(top_k: int, thresholds: ChannelThresholdProfile | None = None).retrieve(skills, sections: Mapping[str, SkillSections], channel_vectors: ChannelVectors | None, vectorizer_kind: Literal["lexical_hash", "semantic"]) -> dict[tuple[str, str], PairSignalsV2]`.
- Retrieval union includes unrestricted behavior-hash pairs, unrestricted equal non-empty execution-hash pairs, activation/procedure/constraint lexical Top-K, and optional activation/procedure dense Top-K. Fixed empty execution hashes never create a pair.
- `RuleDecisionEngine.decide(base, target, signals: PairSignalsV2 | list[Finding] | None) -> RuleDecision` keeps old `decision` values for callers and adds `relation` plus `relation_score`; legacy `CandidateMatch` calls still work.
- Relations are gated exactly as specified: `EXACT_DUPLICATE`, `BEHAVIOR_DUPLICATE_CANDIDATE`, `IMPLEMENTATION_VARIANT_CANDIDATE`, `HIGH_OVERLAP_CANDIDATE`, `CONTAINMENT_CANDIDATE`, `CONSTRAINT_MISMATCH_CANDIDATE`, otherwise `MANUAL_REVIEW`/`PASS`.
- `procedure_coverage_left/right` stays directional; high-overlap score is `min(activation, coverage_left, coverage_right)`; containment evidence states the direction; constraint mismatch is review evidence, not automatic final conflict.

- [ ] **Step 1: Write failing retrieval/decision tests.**

  Cover behavior-hash recall outside Top-K, execution-only variant recall, IDF boilerplate suppression, semantic model candidates not auto-classifying without a profile, full/lite bidirectional coverage, exact/behavior/implementation relations, polarity mismatch, permission difference, environment variant, and the prohibition on `max(lexical, dense, hash_equal)`.

- [ ] **Step 2: Implement channel-aware candidate retrieval.**

  Compute corpus-local IDF per channel, downweight template chunks, cap term frequency, calculate activation lexical/dense scores, directional procedure coverage, constraint action similarity and polarity mismatch, and attach package/behavior/execution/capability/permission/environment evidence. Store hash similarity in `hashed_lexical_similarity`; populate `semantic_similarity` only for `descriptor.kind == "semantic"`.

- [ ] **Step 3: Implement gated relation decisions.**

  Apply exact and behavior fingerprint gates before semantic gates; use independent thresholds from the selected profile; keep uncalibrated semantic candidates at `MANUAL_REVIEW`; never infer conflict from similarity alone; and preserve old legacy decision paths for existing integrations.

- [ ] **Step 4: Update grouping without transitive over-merge.**

  Keep complete-connectivity grouping for same-relation overlap/containment cliques, keep constraint mismatch/permission conflict pairwise, include behavior duplicate and implementation variant groups, and never discard package differences as if they were exact duplicates.

- [ ] **Step 5: Run focused algorithm tests and commit.**

  Run: `python -m pytest tests/core/test_candidates.py tests/test_decisions.py tests/test_audit.py tests/governance/test_analyzer.py tests/governance/test_grouping.py -q`

  ```bash
  git add src/skillcheck/core/candidates.py src/skillcheck/core/retrieval.py src/skillcheck/core/decisions.py src/skillcheck/core/audit.py src/skillcheck/models/audit.py src/skillcheck/models/common.py src/skillcheck/governance/models.py src/skillcheck/governance/analyzer.py tests/core/test_candidates.py tests/test_decisions.py tests/test_audit.py tests/governance/test_analyzer.py tests/governance/test_grouping.py
  git commit -m "feat: classify skill relations with multi-channel signals"
  ```

### Task 7: Expose v2 evidence in reports/MCP while preserving compatibility

**Files:**
- Modify: `src/skillcheck/governance/repository.py: PairEvidence persistence/load and run parameters`
- Modify: `src/skillcheck/governance/reports.py: JSON/Markdown rendering`
- Modify: `src/skillcheck/reports/writer.py: report metadata if needed`
- Modify: `src/skillcheck/mcp/tools.py: evidence payload only; keep tool names and confirmation flow`
- Modify: `src/skillcheck/governance/analyzer.py: policy/vector/fingerprint metadata in run parameters`
- Modify: `src/skillcheck/governance/redaction.py: ensure new evidence remains bounded/redacted`
- Test: `tests/governance/test_evidence.py`
- Test: `tests/governance/test_reports.py`
- Test: `tests/mcp/test_tools.py`
- Test: `tests/mcp/test_server.py`
- Test: `tests/mcp/test_contract.py`

**Interfaces:**
- `PairEvidence` JSON adds `signals_version="v2"`, fingerprint flags, channel scores, directional coverage, `constraint_polarity_mismatch`, `relation_score`, vectorizer descriptor/signature and threshold profile; old persisted `PairSignals` JSON remains readable with defaults.
- `analysis_runs.parameters_json` records hash/section/feature revisions, vectorizer descriptor, locality, model signature and threshold profile, with no Skill body or secrets.
- `EvidencePage` and report JSON/Markdown show package/behavior/execution relation, channel-specific scores, coverage direction, polarity mismatch and model degradation; evidence pagination and `include_body` redaction remain unchanged.

- [ ] **Step 1: Write failing compatibility/report tests.**

  Load a historical run containing old signals, assert v2 runs expose all new channels, assert no single `semantic_similarity` max score is rendered as a universal score, assert model signatures and threshold profile are present, and verify MCP tool names/confirmation/redaction are unchanged.

- [ ] **Step 2: Implement v2 persistence and rendering.**

  Serialize new fields additively, parse historical rows through compatibility defaults, render relation-specific evidence and explicit model kind (`lexical_hash` vs `semantic`), and retain bounded excerpts/hashes only.

- [ ] **Step 3: Run MCP/report tests and commit.**

  Run: `python -m pytest tests/governance/test_evidence.py tests/governance/test_reports.py tests/mcp/test_tools.py tests/mcp/test_server.py tests/mcp/test_contract.py -q`

  ```bash
  git add src/skillcheck/governance/repository.py src/skillcheck/governance/reports.py src/skillcheck/reports/writer.py src/skillcheck/mcp/tools.py src/skillcheck/governance/analyzer.py src/skillcheck/governance/redaction.py tests/governance/test_evidence.py tests/governance/test_reports.py tests/mcp
  git commit -m "feat: expose segmented relation evidence through reports and MCP"
  ```

### Task 8: Add calibrated evaluation gate and documentation

**Files:**
- Create: `scripts/experiments/segmented_vector_evaluation.py`
- Create: `docs/superpowers/experiments/2026-10-03-segmented-vector-evaluation.md`
- Modify: `README.md: embedding configuration and relation semantics`
- Modify: `docs/superpowers/specs/2026-10-03-skill-fingerprint-segmented-representation-design.md: implementation status only after code is verified`
- Test: `tests/acceptance/test_governance_algorithm_p0_p1.py`
- Test: `tests/acceptance/test_user_journeys.py`

**Interfaces:**
- `scripts/experiments/segmented_vector_evaluation.py` accepts a fixture directory and optional model config, emits per-relation `precision`, `recall`, `f1`, `support`, `recall_at_20`, and boilerplate false-positive rate as JSON/Markdown; it never changes the Catalog.
- Production defaults may only be marked calibrated after at least 100 manually labeled Skill pairs containing duplicate, containment, variant, constraint mismatch and unrelated classes.

- [ ] **Step 1: Write failing acceptance checks.**

  Assert the default offline configuration completes all fixture cases, the optional model is explicit, old CLI/MCP journeys still require user confirmation for writes, and `MIRRORED_COPY` remains monitor-only.

- [ ] **Step 2: Implement the evaluation harness.**

  Run the same retriever/decision path as governance analysis, report each relation separately, and refuse to mark a semantic model/profile as default when labeled support is below 100 pairs or any gate metric fails: candidate Recall@20 ≥ 0.95, exact duplicate precision 1.0, behavior duplicate precision ≥ 0.98, boilerplate high-overlap false-positive rate ≤ 0.02.

- [ ] **Step 3: Document configuration and limitations.**

  Explain hash fallback, local SentenceTransformer opt-in, model signature invalidation, threshold-profile calibration, privacy boundary for future remote adapters, and why semantic similarity is not conflict probability.

- [ ] **Step 4: Run the complete proportionate verification set.**

  Run:

  ```bash
  python -m pytest tests/acceptance/test_fingerprint_regression.py tests/acceptance/test_vectorization_regression.py tests/acceptance/test_governance_algorithm_p0_p1.py tests/acceptance/test_user_journeys.py -q
  python -m ruff check src tests scripts/experiments/segmented_vector_evaluation.py
  git diff --check
  ```

  Expected: all targeted tests and lint pass; if the full suite remains dependency-blocked, record the exact blocker and do not call it a product regression.

- [ ] **Step 5: Commit the evaluation gate and docs.**

  ```bash
  git add scripts/experiments/segmented_vector_evaluation.py docs/superpowers/experiments/2026-10-03-segmented-vector-evaluation.md README.md docs/superpowers/specs/2026-10-03-skill-fingerprint-segmented-representation-design.md tests/acceptance
  git commit -m "docs: add segmented vector evaluation gate and configuration guide"
  ```

## Self-Review Checklist

- Spec coverage: Tasks 1–2 cover fixtures and layered fingerprints; Task 3 covers sections, polarity and IDF; Task 4 covers the registry interface/config/privacy/signatures; Task 5 covers segment storage and lifecycle; Task 6 covers retrieval/PairSignalsV2/relations; Task 7 covers reports/MCP/history; Task 8 covers the 100-pair calibration gate and metrics.
- Type consistency: `EmbeddingChannel`, `SkillSections`, `VectorizationInput`, `VectorizerDescriptor`, `ChannelVectors`, `PairSignalsV2`, `FingerprintResult` and `SegmentVectorRecord` are named once and consumed by later tasks exactly as declared.
- Compatibility: old `content_hash`, `instruction_hash`, `vectors`, `PairSignals`, embedding class names, CLI/MCP tools, report redaction and write confirmation remain readable or aliased; new analysis selects only current v2 signatures.
- Review focus coverage: metadata/format and unreadable scripts are pinned in Tasks 1–2; boilerplate and polarity are pinned in Tasks 3/6; model failures, malformed batches and signature isolation are pinned in Tasks 4/5.
- Proportion: the plan specifies signatures, files, tests and acceptance gates without prescribing implementation bodies beyond hashing, chunking, validation and relation invariants that must be identical across agents.
