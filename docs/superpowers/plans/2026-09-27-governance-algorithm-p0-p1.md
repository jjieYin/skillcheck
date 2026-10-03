# Skillcheck Governance Algorithm P0–P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Skillcheck 治理审查链路的配置失效、向量不一致、scope 无效、风险与关系混合及链式误聚类问题，并加入默认离线的中英文混合候选召回、双哈希和统一规范/安全校验。

**Architecture:** 由 `GovernancePolicy` 统一注入算法配置，Catalog 只生成和读取当前 embedding 签名的向量，`ScopeSelector` 先确定完整输入集合。审查过程把 Skill 自身 findings 与 Pair relation 分开，使用 hash、Unicode 词法和可选向量三路召回，再用结构化 `PairSignals` 判定关系并以完全连接约束分组；当前 Agent 仍负责语义终审。

**Tech Stack:** Python 3.11、Pydantic v2、SQLite/FTS5、NumPy、可选 sentence-transformers、可选 NVIDIA SkillSpector、pytest、Ruff、MCP stdio

**Spec:** `docs/superpowers/specs/2026-09-27-governance-algorithm-p0-p1-design.md`

## Global Constraints

- 保留四个 MCP 工具名称和参数入口；不得新增第二个 Agent 进程。
- 证据必须继续分页、正文截断并脱敏；没有用户确认不得持久化 review 或 sync group。
- 默认安装不得新增必装模型或联网依赖；hash/Unicode 词法路径必须离线可用。
- `MIRRORED_COPY` 继续保持 `monitor_only`；不得修改、删除、重命名或安装用户 Skill。
- 所有选中 Skill 必须参与分析；`thresholds.top_k` 只控制每路候选邻居数，不得切片输入集合。
- 内建来源安全检查始终启用；`security.enabled` 只控制配置后的外部 SkillSpector。
- P2 的训练、黄金集、自动阈值学习和发布指标门禁不在本计划内。
- 测试命令必须显式设置 `$env:PYTHONPATH = "src"`，避免把 src-layout 导入失败误判为算法失败。

## Review Focus

- 同一快照同时存在旧模型和当前模型向量时，只允许使用当前签名；Task 2 必须覆盖。
- `scope="project"` 在不同项目有同名 Skill 时只选择当前项目，不能扩大为所有项目；Task 3 必须覆盖。
- 高危 Skill 与正常但相似的 Skill 比较时，关系结果不能变成安全组，且高危 finding 仍必须保留；Task 4 必须覆盖。
- A≈B、B≈C、A≉C 时不得生成三成员相似组；Task 5 必须覆盖。
- CJK 无空格文本、拉丁文本和混合文本都必须稳定产生候选，且无向量时不能崩溃；Task 7 必须覆盖。

---

## 文件职责与实施顺序

新增文件：

- `src/skillcheck/governance/policy.py`：从 `AppConfig` 生成唯一治理策略对象。
- `src/skillcheck/governance/selection.py`：解析并执行 library/source scope 选择。
- `src/skillcheck/core/features.py`：文本规范化、Unicode n-gram、能力集合和 `PairSignals`。
- `src/skillcheck/core/candidates.py`：合并 hash、词法和向量候选。
- `src/skillcheck/core/validation.py`：编排内建校验与可选 SkillSpector。
- `tests/governance/test_policy.py`、`test_selection.py`、`test_grouping.py`：P0 专项回归。
- `tests/core/test_candidates.py`、`test_features.py`：P1 候选与特征回归。
- `tests/acceptance/test_governance_algorithm_p0_p1.py`：跨入口验收。

现有文件继续保持单一职责：

- `catalog/reconcile.py` 只负责快照、哈希和向量生命周期；
- `core/decisions.py` 只判断两个 Skill 的关系；
- `core/audit.py` 只组织候选、关系和分组；
- `governance/analyzer.py` 只编排选择、校验、审查与持久化；
- `governance/repository.py` 只持久化 run、证据和 review 上下文。

Task 1–5 是 P0，完成 Task 5 后必须停在 P0 Gate 供审阅。Task 6–9 是 P1，只有 P0 Gate 通过后继续。

---

### Task 1: 建立唯一的 GovernancePolicy 并接通所有生产入口

**解决的问题:** `ThresholdConfig`、embedding 和 security 配置已经存在，但生产分析器与规则引擎仍可能使用各自默认值，导致修改配置后结果不变。

**Files:**
- Create: `src/skillcheck/governance/policy.py`
- Modify: `src/skillcheck/config/models.py`
- Modify: `src/skillcheck/embeddings.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/app/context.py`
- Modify: `src/skillcheck/mcp/tools.py`
- Test: `tests/governance/test_policy.py`
- Test: `tests/config/test_loader.py`
- Test: `tests/commands/test_groups.py`
- Test: `tests/mcp/test_tools.py`

**Interfaces:**
- Produces: `embedding_signature(config: EmbeddingConfig) -> str`。
- Produces: `GovernancePolicy.from_config(config: AppConfig, *, project_path: Path | None = None) -> GovernancePolicy`。
- Produces: `GovernanceAnalyzer(catalog: CatalogRepository, runtime: McpRuntime | None = None, *, staging_root: Path | str | None = None, source_limits: SourceLimits | None = None, policy: GovernancePolicy | None = None)`；测试可省略 policy，生产工厂必须显式传入。
- Consumes: 现有 `ThresholdConfig`、`SecurityConfig` 和 `EmbeddingConfig`。

- [ ] **Step 1: 为非默认阈值编写失败测试**

在 `tests/governance/test_policy.py` 添加：

```python
def test_configured_overlap_threshold_reaches_decision_engine(repository, config):
    config.thresholds.overlap_similarity = 0.70
    analyzer = GovernanceAnalyzer(
        repository,
        policy=GovernancePolicy.from_config(config),
    )
    result = analyze_pair(analyzer, similarity=0.75)
    assert relation_names(result) == {"HIGH_OVERLAP_CANDIDATE"}
```

再添加 `top_k=1` 测试，断言每个 Skill 的向量候选不超过一条，但 `skills_considered` 仍等于完整输入数量。

- [ ] **Step 2: 运行定向测试并确认旧实现失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/governance/test_policy.py tests/config/test_loader.py -q
```

Expected: FAIL，生产分析器尚无 `GovernancePolicy`，非默认阈值没有进入 auditor。

- [ ] **Step 3: 定义策略与 embedding 签名**

`EmbeddingConfig` 新增带默认值的 `algorithm_revision: str = "2"`，旧配置可直接加载。实现精确接口 `embedding_signature(config: EmbeddingConfig) -> str`。`GovernancePolicy` 使用 frozen dataclass，字段依次为 `thresholds: ThresholdConfig`、`embedding_signature: str`、`security: SecurityConfig`、`project_path: Path | None = None`，并提供 `from_config(config: AppConfig, *, project_path: Path | None = None) -> GovernancePolicy`。

签名格式必须为 `<backend>:<model-or-id>:d<dimensions>:r<algorithm-revision>`，并规范化首尾空格。

- [ ] **Step 4: 将策略注入分析器、auditor 和规则引擎**

`GovernanceAnalyzer._analyze()` 必须使用：

```python
engine = RuleDecisionEngine(self.policy.thresholds)
auditor = LibraryAuditor(
    top_k=self.policy.thresholds.top_k,
    decision_engine=engine,
)
```

不得再用输入 Skill 数量构造 `top_k`。保留当前完整输入行为，Task 3 再删除内部 `limit` 遗留接口。

- [ ] **Step 5: 接通 CLI、扫描、安装预检与 MCP 工厂**

`build_scan_pipeline()`、`build_add_pipeline()` 和 `SkillcheckMcpTools._governance()` 都从同一 `AppConfig` 创建策略。MCP 使用 `runtime.project_path`；普通 CLI 使用当前工作目录或显式项目路径。

- [ ] **Step 6: 验证配置传播**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/governance/test_policy.py tests/config/test_loader.py tests/commands/test_groups.py tests/mcp/test_tools.py -q
```

Expected: PASS，非默认 overlap、variant、conflict 和 top_k 均可通过测试观察到。

- [ ] **Step 7: 提交 Task 1**

```powershell
git add src/skillcheck/governance/policy.py src/skillcheck/config/models.py src/skillcheck/embeddings.py src/skillcheck/governance/analyzer.py src/skillcheck/app/context.py src/skillcheck/mcp/tools.py tests/governance/test_policy.py tests/config/test_loader.py tests/commands/test_groups.py tests/mcp/test_tools.py
git commit -m "fix: wire governance policy into analysis"
```

---

### Task 2: 修复 MCP 增量向量与模型签名一致性

**解决的问题:** MCP 可以在没有 embedding 的情况下更新快照；分析器读取全部模型向量并选择排序第一条；缺失或维度错误的向量会导致审查退化或被静默跳过。

**Files:**
- Modify: `src/skillcheck/mcp/runtime.py`
- Modify: `src/skillcheck/catalog/reconcile.py`
- Modify: `src/skillcheck/catalog/repository.py`
- Modify: `src/skillcheck/embeddings.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Test: `tests/mcp/test_runtime.py`
- Test: `tests/catalog/test_reconcile.py`
- Test: `tests/catalog/test_repository.py`
- Test: `tests/governance/test_analyzer.py`

**Interfaces:**
- Consumes: `GovernancePolicy.embedding_signature`。
- Produces: `CatalogRepository.get_vectors(model: str)` 作为分析路径的必传调用；保留可选参数只供诊断代码使用。
- Produces: `CatalogRepository.has_vector(snapshot_id: str, model: str) -> bool`。
- Produces: backend 的 `model_id` 必须等于 `embedding_signature(config)`。

- [ ] **Step 1: 编写当前签名选择和 MCP 回填失败测试**

覆盖三种情况：

1. 同一 snapshot 保存 `old-model` 与当前签名，分析只使用当前签名；
2. MCP start 对没有当前签名向量的现有 snapshot 补算向量；
3. MCP 文件变更生成新 snapshot 后，新 snapshot 与向量在同一次 reconcile 完成。

维度损坏测试必须断言返回 `AUDIT002`，而不是没有任何提示地跳过候选。

- [ ] **Step 2: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/mcp/test_runtime.py tests/catalog/test_reconcile.py tests/catalog/test_repository.py tests/governance/test_analyzer.py -q
```

- [ ] **Step 3: 让所有 reconciler 使用配置 backend**

`McpRuntime._ensure_catalog()` 必须构造：

```python
CatalogReconciler(
    self.repository,
    embedding=backend_from_config(self.config.embedding),
)
```

初始化、手工 sync、scan 和 MCP 不得存在第二套构造规则。

- [ ] **Step 4: 对未变快照补齐当前签名向量**

在 reconcile 的相同内容快速路径中检查 `has_vector(snapshot_id, backend.model_id)`。缺失时重新解析该 Skill、编码并保存向量；已有当前签名时保持快速跳过。`_save_vector()` 使用 `ON CONFLICT(snapshot_id, model) DO UPDATE`，保证重试幂等。

- [ ] **Step 5: 分析器只读取当前签名并检查维度**

`GovernanceAnalyzer._vectors_for()` 调用 `get_vectors(self.policy.embedding_signature)`。同一批向量维度不一致时，为受影响 skill 生成带 skill ID、模型签名和实际维度的 `AUDIT002`；不得把不一致当作普通低相似度。

- [ ] **Step 6: 运行向量生命周期回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/mcp/test_runtime.py tests/catalog/test_reconcile.py tests/catalog/test_repository.py tests/governance/test_analyzer.py tests/test_embeddings.py -q
```

Expected: PASS，旧模型向量仍保留但不被当前分析读取。

- [ ] **Step 7: 提交 Task 2**

```powershell
git add src/skillcheck/mcp/runtime.py src/skillcheck/catalog/reconcile.py src/skillcheck/catalog/repository.py src/skillcheck/embeddings.py src/skillcheck/governance/analyzer.py tests/mcp/test_runtime.py tests/catalog/test_reconcile.py tests/catalog/test_repository.py tests/governance/test_analyzer.py tests/test_embeddings.py
git commit -m "fix: keep catalog vectors on the active model signature"
```

---

### Task 3: 实现 scope 并彻底分离输入数量与候选数量

**解决的问题:** `scope` 参数被接受但没有过滤效果；内部 `limit` 容易再次把完整分析退化为前 N 条分析。

**Files:**
- Create: `src/skillcheck/governance/selection.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/mcp/server.py`
- Modify: `src/skillcheck/mcp/tools.py`
- Modify: `src/skillcheck/mcp/instructions.py`
- Test: `tests/governance/test_selection.py`
- Test: `tests/governance/test_analyzer.py`
- Test: `tests/governance/test_source_preflight.py`
- Test: `tests/mcp/test_contract.py`

**Interfaces:**
- Produces: `AnalysisScope(StrEnum)`，值为 `all/global/project/custom`。
- Produces: `ScopeSelector.select_library(snapshots, roots, scope, *, project_path) -> list[SkillSnapshot]`。
- Produces: `ScopeSelector.select_catalog_for_source(snapshots: list[SkillSnapshot], roots: list[LibraryRoot], scope: AnalysisScope | str, *, project_path: Path | None) -> list[SkillSnapshot]`，暂存来源由 analyzer 始终加入。
- Removes: `limit` from `GovernanceAnalyzer.analyze()`、`analyze_library()`、`analyze_source()` 和 `_analyze()`。

- [ ] **Step 1: 编写四种 scope 与非法 scope 测试**

至少构造 global、当前 project、其他 project、custom 四个根目录。断言：

```python
assert ids(select("all")) == all_ids
assert ids(select("global")) == global_ids
assert ids(select("project", project_path=current)) == current_project_ids
assert ids(select("custom")) == custom_ids
with pytest.raises(ValueError, match="scope"):
    select("unknown")
```

来源模式测试断言 staged Skill 始终存在，而 catalog 对照集服从 scope。

- [ ] **Step 2: 编写完整参与数量测试**

创建 168 个 Skill，设置 `top_k=2`，断言 `skills_considered == 168`。重复项放在排序尾部并确保 hash 关系仍被发现。

- [ ] **Step 3: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/governance/test_selection.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/mcp/test_contract.py -q
```

- [ ] **Step 4: 实现 ScopeSelector 并删除 limit 遗留**

project scope 必须比较规范化的 `LibraryRoot.project_path` 与策略中的当前项目路径。没有当前项目路径时抛出明确错误，不能回退为所有 project roots 或 `all`。

- [ ] **Step 5: 更新 MCP 描述但保持 schema 兼容**

`scope` 仍为字符串参数，描述明确列出四个值。MCP 继续不暴露 `limit`；四个工具名称不变。

- [ ] **Step 6: 运行 scope 与 MCP 回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/governance/test_selection.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/mcp -q
```

- [ ] **Step 7: 提交 Task 3**

```powershell
git add src/skillcheck/governance/selection.py src/skillcheck/governance/analyzer.py src/skillcheck/mcp/server.py src/skillcheck/mcp/tools.py src/skillcheck/mcp/instructions.py tests/governance/test_selection.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/mcp
git commit -m "fix: enforce governance analysis scope"
```

---

### Task 4: 分离 Skill findings 与 Pair relation，并修正冲突门控

**解决的问题:** 任意一侧有高危 finding 会把整个 pair 判为 `UNSAFE`；权限冲突不使用 `conflict_similarity`，并且同资源的多个权限模式会相互覆盖。

**Files:**
- Create: `src/skillcheck/core/features.py`
- Modify: `src/skillcheck/core/decisions.py`
- Modify: `src/skillcheck/core/audit.py`
- Modify: `src/skillcheck/models/audit.py`
- Modify: `src/skillcheck/governance/models.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/governance/repository.py`
- Modify: `src/skillcheck/governance/reports.py`
- Test: `tests/core/test_features.py`
- Test: `tests/test_decisions.py`
- Test: `tests/test_audit.py`
- Test: `tests/governance/test_reports.py`

**Interfaces:**
- Produces: `PairSignals` dataclass with `semantic_similarity`, optional dense/lexical/capability similarities, permission/environment flags and hash flags。
- Changes: `RuleDecisionEngine.decide(base: SkillRecord, target: SkillRecord, signals: PairSignals) -> RuleDecision`。
- Produces: `SkillFinding(BaseModel)` with `skill_id: str` and `finding: Finding`。
- Adds: `AnalyzeResult.skill_findings: list[SkillFinding]`；兼容保留 `deterministic_findings`。

- [ ] **Step 1: 编写风险与关系正交测试**

构造带 `SEC002` 的 A 和正常 B：

- A/B 语义低于阈值时没有 pair group；
- A 的 `SkillFinding` 仍存在；
- A/B 语义高于 overlap 时只生成 overlap group，同时 A 的安全 finding 独立存在；
- B 不得被标记为安全问题。

- [ ] **Step 2: 编写 conflict 阈值和多权限模式测试**

同一资源 read/write 且相似度 `conflict_similarity - 0.01` 必须 PASS；达到阈值才生成 conflict。单个 Skill 同时声明 `database-read` 和 `database-write` 时不得因字典覆盖丢失任一模式。

- [ ] **Step 3: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/core/test_features.py tests/test_decisions.py tests/test_audit.py tests/governance/test_reports.py -q
```

- [ ] **Step 4: 引入 PairSignals，移除 RuleDecisionEngine 的 findings 参数**

`RuleDecisionEngine` 只根据两个 Skill 和 `PairSignals` 输出 duplicate/conflict/variant/similar/pass。`Decision.UNSAFE` 保留给安装和人工审查模型，但不能由 pair relation 引擎返回。

- [ ] **Step 5: 独立生成并持久化 SkillFinding**

`LibraryAuditor` 不再创建 `SECURITY_ISSUE` 或 `QUALITY_ISSUE` group。`AnalyzeSummary.security_issues` 与 `quality_issues` 改为对应 findings 数量，并在报告中按 skill ID 展示。

`analysis_runs.parameters_json` 使用：

```json
{
  "skill_findings": [{
    "skill_id": "skill-a",
    "finding": {
      "rule_id": "SEC002",
      "severity": "high",
      "message": "Skill appears to contain a hardcoded credential.",
      "evidence_path": "SKILL.md",
      "remediation": "Remove the credential."
    }
  }],
  "local_findings": [],
  "trigger_source": "agent_intent"
}
```

`local_findings` 保留一个版本用于旧报告读取。

- [ ] **Step 6: 运行关系、报告与安装回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/core/test_features.py tests/test_decisions.py tests/test_audit.py tests/governance/test_analyzer.py tests/governance/test_reports.py tests/test_installer.py -q
```

- [ ] **Step 7: 提交 Task 4**

```powershell
git add src/skillcheck/core/features.py src/skillcheck/core/decisions.py src/skillcheck/core/audit.py src/skillcheck/models/audit.py src/skillcheck/governance/models.py src/skillcheck/governance/analyzer.py src/skillcheck/governance/repository.py src/skillcheck/governance/reports.py tests/core/test_features.py tests/test_decisions.py tests/test_audit.py tests/governance/test_reports.py
git commit -m "fix: separate skill findings from pair relations"
```

---

### Task 5: 用成对证据和完全连接约束替换单链分组

**解决的问题:** 当前连通分量会把 A≈B、B≈C 推导成 A/B/C 一组；多成员组的 `similarity` 来自第一条文本证据，不能代表全组。

**Files:**
- Modify: `src/skillcheck/models/audit.py`
- Modify: `src/skillcheck/core/audit.py`
- Modify: `src/skillcheck/governance/models.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/governance/repository.py`
- Test: `tests/governance/test_grouping.py`
- Test: `tests/governance/test_evidence.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Converts: `PairEvidence` to a Pydantic model with `source_skill_id`、`target_skill_id`、`relation`、`signals`、`confidence`、`evidence`、`recommendations`。
- Adds: `AuditGroup.pair_evidence` and min/mean/max similarity。
- Adds: `CandidateGroupSummary.min_similarity`、`mean_similarity`、`max_similarity`；兼容字段 `similarity == mean_similarity`。
- Adds: `EvidencePage.pair_evidence`，内容继续经过脱敏和分页边界控制。

- [ ] **Step 1: 编写链式三元组失败测试**

构造三条已知信号：A-B=0.91 overlap、B-C=0.90 overlap、A-C=0.40 pass。断言不得出现 `{A,B,C}`；允许稳定输出 `{A,B}` 与 `{B,C}` 两个候选组。

再构造 A-B、A-C、B-C 都为 overlap，断言生成三成员组，统计值分别等于三条边的 min/mean/max。

- [ ] **Step 2: 编写 conflict 始终二元测试**

即使 A-B 和 B-C 都是 conflict，也必须输出两个二元组，不得生成三成员 conflict group。

- [ ] **Step 3: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/governance/test_grouping.py tests/governance/test_evidence.py tests/test_audit.py -q
```

- [ ] **Step 4: 实现确定性完全连接分组**

按 `(-semantic_similarity, source_id, target_id)` 排序候选边。仅对 overlap/variant 尝试合并：所有跨组 member pair 都存在相同 relation 边时才合并；缺边视为不能合并。conflict 每条边独立成组。

- [ ] **Step 5: 持久化 pair evidence**

`GovernanceRepository.save_run()` 将每个 group 的成对信号和统计写入现有 `evidence` 表，`kind="pair_signals"`。读取历史 run 没有该记录时返回空列表和旧 `score`。

- [ ] **Step 6: 运行分组、持久化和 review 回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/governance/test_grouping.py tests/governance/test_evidence.py tests/governance/test_reviews.py tests/governance/test_reports.py tests/test_audit.py -q
```

- [ ] **Step 7: 提交 Task 5**

```powershell
git add src/skillcheck/models/audit.py src/skillcheck/core/audit.py src/skillcheck/governance/models.py src/skillcheck/governance/analyzer.py src/skillcheck/governance/repository.py tests/governance/test_grouping.py tests/governance/test_evidence.py tests/test_audit.py
git commit -m "fix: prevent chained governance groups"
```

---

## P0 Gate：正确性里程碑

- [ ] **Step 1: 运行 P0 定向测试**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_audit.py tests/test_decisions.py tests/test_embeddings.py tests/catalog tests/governance tests/mcp -q
```

- [ ] **Step 2: 运行全量回归和 Ruff**

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
python -m ruff check src tests
```

- [ ] **Step 3: 人工审阅 P0 输出**

审阅者确认：配置值已进入 run parameters；当前签名向量完整；四种 scope 结果正确；安全/质量 findings 不改变 pair relation；链式三元组没有合并。P0 未通过时不得开始 Task 6。

---

### Task 6: 升级 Catalog v6，加入 instruction hash 与官方字段

**解决的问题:** 当前 `content_hash` 包含所有资产，导致指令完全相同但附件不同的 Skill 无法被识别；解析器未保存 Agent Skills 的官方可选字段，name fallback 也会掩盖规范问题。

**Files:**
- Modify: `src/skillcheck/catalog/schema.sql`
- Modify: `src/skillcheck/catalog/migrations.py`
- Modify: `src/skillcheck/catalog/database.py`
- Modify: `src/skillcheck/catalog/models.py`
- Modify: `src/skillcheck/catalog/repository.py`
- Modify: `src/skillcheck/catalog/reconcile.py`
- Modify: `src/skillcheck/core/parser.py`
- Modify: `src/skillcheck/models/skill.py`
- Modify: `src/skillcheck/governance/scopes.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Test: `tests/catalog/test_schema.py`
- Test: `tests/catalog/test_migrations.py`
- Test: `tests/catalog/test_reconcile.py`
- Test: `tests/test_parser.py`
- Test: `tests/governance/test_scopes.py`

**Interfaces:**
- Produces: `instruction_hash(root: Path) -> str`，与现有 package `content_hash(root)` 分离。
- Adds to `SkillRecord`/`SkillSnapshot`: `instruction_hash`、`license`、`compatibility`、`metadata`、`allowed_tools`。
- Catalog v6 columns: `instruction_hash`、`license`、`compatibility`、`metadata_json`、`allowed_tools_json`。
- Keeps: `content_hash` 继续表示完整包哈希，不重命名数据库列。

- [ ] **Step 1: 编写双哈希和官方字段测试**

创建两个 SKILL.md 内容相同但 assets 不同的包，断言 package hash 不同、instruction hash 相同。再验证换行符和 YAML key 顺序变化不会改变 instruction hash，但正文有效字符变化会改变。

解析测试必须覆盖 `license`、`compatibility`、对象型 `metadata` 和字符串/列表型 `allowed-tools`。

- [ ] **Step 2: 编写 v5→v6 原子迁移测试**

从真实 v5 fixture 迁移，断言：

- schema version 为 6；
- 新列存在；
- 旧行的 `instruction_hash` 初始等于 `content_hash`；
- 迁移故障会回滚为完整 v5，而不是半迁移数据库。

- [ ] **Step 3: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/catalog/test_schema.py tests/catalog/test_migrations.py tests/catalog/test_reconcile.py tests/test_parser.py tests/governance/test_scopes.py -q
```

- [ ] **Step 4: 实现稳定 instruction hash**

解析 YAML 映射后以 sorted-key JSON 编码，正文统一为 `\n`、删除每行尾部空白、保证文件末尾单一换行。哈希只覆盖规范化后的 SKILL.md 语义内容，不覆盖 assets。

- [ ] **Step 5: 实现 Catalog v6 与模型字段**

新增 `V5_TO_V6_SQL`，`CatalogDatabase.initialize()` 支持 v4→v5→v6 顺序迁移及直接 v5→v6。reconcile 发现保守回填值时必须重算真实 instruction hash，即使目录元数据指纹没有变化。

- [ ] **Step 6: 调整重复语义**

ScopeClassifier 仍只用 package hash 生成 `EXACT_DUPLICATE`/`MIRRORED_COPY`。instruction hash 相同但 package hash 不同的 pair 进入 `HIGH_OVERLAP_CANDIDATE`，pair evidence 写入 `instruction_hash_equal=true` 和“instructions identical; package assets differ”。

- [ ] **Step 7: 运行迁移、解析和重复分类回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/catalog tests/test_parser.py tests/governance/test_scopes.py tests/governance/test_analyzer.py tests/test_audit.py -q
```

- [ ] **Step 8: 提交 Task 6**

```powershell
git add src/skillcheck/catalog src/skillcheck/core/parser.py src/skillcheck/models/skill.py src/skillcheck/governance/scopes.py src/skillcheck/governance/analyzer.py tests/catalog tests/test_parser.py tests/governance/test_scopes.py
git commit -m "feat: distinguish instruction and package hashes"
```

---

### Task 7: 实现 Unicode-aware 混合候选召回

**解决的问题:** 当前 feature-hash 按非字母数字切分，中文无空格句子通常成为一个 token；固定字段标签产生噪声；source 模式又使用另一套 128 维词法向量。

**Files:**
- Create: `src/skillcheck/core/candidates.py`
- Modify: `src/skillcheck/core/features.py`
- Modify: `src/skillcheck/embeddings.py`
- Modify: `src/skillcheck/core/retrieval.py`
- Modify: `src/skillcheck/core/audit.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/catalog/reconcile.py`
- Test: `tests/core/test_candidates.py`
- Test: `tests/core/test_features.py`
- Test: `tests/test_embeddings.py`
- Test: `tests/test_audit.py`
- Test: `tests/governance/test_analyzer.py`

**Interfaces:**
- Produces: `activation_text(skill) -> str`、`procedure_text(skill) -> str`、`lexical_features(text) -> Counter[str]`。
- Produces: `HybridCandidateRetriever(top_k: int).retrieve(skills, vectors) -> dict[tuple[str, str], PairSignals]`。
- Consumes: Task 4 的 `PairSignals` 和 Task 6 的 instruction/package hashes。
- Removes: `GovernanceAnalyzer` 的 `_lexical_vector()` source-only 分支。

- [ ] **Step 1: 编写 CJK、拉丁与混合文本特征测试**

断言无空格中文生成多个字符 2–4 gram；英文生成规范化 unigram/bigram；大小写、连续空白和 Markdown 标记变化不改变核心特征。固定标签 `name:`、`description:` 等不得进入文本。

- [ ] **Step 2: 编写三路召回测试**

覆盖：

- 相同 instruction hash 永远召回，即使不在词法/向量 top-k；
- 中文近似描述在 hash backend 下进入词法候选；
- 低词面重合的同义文本可由 stub dense backend 召回；
- 无 dense vector 时仍由词法通道工作并返回 `AUDIT001`；
- 每一路最多 `top_k`，合并后稳定去重。

- [ ] **Step 3: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/core/test_candidates.py tests/core/test_features.py tests/test_embeddings.py tests/test_audit.py tests/governance/test_analyzer.py -q
```

- [ ] **Step 4: 实现规范化文本与 Unicode 特征**

CJK 字符使用 2–4 gram；拉丁字母数字序列使用 casefold 后的 unigram/bigram。词法相似度使用归一化 cosine，空特征返回 0.0。能力集合分别对 allowed tools、项目 tools、permissions、environments、inputs、outputs 做带字段名的集合 Jaccard，禁止不同字段同名互相匹配。

- [ ] **Step 5: 更新 hash embedding 文本和算法**

`skill_embedding_text()` 只拼接规范化 activation/procedure 内容，不添加固定英文标签。`HashEmbeddingBackend` 使用 `lexical_features()`；模型签名中的 revision 已为 `r2`，因此旧向量不会被复用。

- [ ] **Step 6: 实现 HybridCandidateRetriever**

分别获取 instruction-hash、词法 top-k、dense top-k，再以稳定 pair key 合并成 `PairSignals`。`semantic_similarity` 取可用 dense/lexical 的最大值；capability similarity 作为证据，不引入额外加权总分。

- [ ] **Step 7: 统一 library/source 候选路径**

source 模式的暂存 Skill 和选中 catalog Skill 使用同一 retriever；只保留至少一侧属于 staged source 的 pair。删除 `_lexical_vector()`、`_max_similarity()` 和 128 维 source 专用逻辑。

- [ ] **Step 8: 运行候选、分析和来源回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/core/test_candidates.py tests/core/test_features.py tests/test_embeddings.py tests/test_audit.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py -q
```

- [ ] **Step 9: 提交 Task 7**

```powershell
git add src/skillcheck/core/candidates.py src/skillcheck/core/features.py src/skillcheck/embeddings.py src/skillcheck/core/retrieval.py src/skillcheck/core/audit.py src/skillcheck/governance/analyzer.py src/skillcheck/catalog/reconcile.py tests/core/test_candidates.py tests/core/test_features.py tests/test_embeddings.py tests/test_audit.py tests/governance/test_analyzer.py
git commit -m "feat: add hybrid multilingual candidate retrieval"
```

---

### Task 8: 统一官方规范、内建安全与可选 SkillSpector

**解决的问题:** 库级分析只检查少数正文字段；完整 BuiltinValidator 主要用于来源预检；SkillSpector 配置和适配器未进入生产路径；fallback name 会掩盖缺失 name。

**Files:**
- Create: `src/skillcheck/core/validation.py`
- Modify: `src/skillcheck/core/validators.py`
- Modify: `src/skillcheck/core/parser.py`
- Modify: `src/skillcheck/skillspector.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/app/context.py`
- Modify: `src/skillcheck/mcp/tools.py`
- Test: `tests/test_validators.py`
- Test: `tests/governance/test_analyzer.py`
- Test: `tests/governance/test_source_preflight.py`
- Test: `tests/security/test_source_attacks.py`

**Interfaces:**
- Produces: `CompositeSkillValidator.scan(root: Path, skill: SkillRecord) -> list[Finding]`。
- Constructor: `CompositeSkillValidator(builtin: BuiltinValidator, external: SkillSpectorAdapter | None = None)`。
- Consumes: `SecurityConfig`；只有 enabled 且 command 非空时工厂创建 external adapter。

- [ ] **Step 1: 编写官方字段规范测试**

至少覆盖：缺失 name、缺失 description、非法 name、name 与目录不一致、description 超过 1024 字符、allowed-tools 类型错误、正文超过 500 行。缺失 name 的 Skill 仍可用目录名索引，但必须返回 `FMT001`。

- [ ] **Step 2: 编写 library/source 规则一致性测试**

同一个 Skill 分别放在 catalog 和 staged source，断言内建 FMT/QLT/SEC rule IDs 相同。安全扫描必须覆盖 scripts 和 references 中的文本文件，不只扫描 SKILL.md。

- [ ] **Step 3: 编写 SkillSpector 启用矩阵测试**

覆盖：

- `enabled=false` 且有 command：不执行外部进程；
- `enabled=true` 但 command 为空：只运行内建规则，不产生每 Skill 的 CAP001；
- enabled 且 command 存在：合并外部 findings；
- 外部超时/JSON 错误：返回非阻断 CAP002，内建结果仍保留。

- [ ] **Step 4: 运行测试确认失败**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_validators.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/security/test_source_attacks.py -q
```

- [ ] **Step 5: 扩展 BuiltinValidator**

从原始 frontmatter 判断字段是否存在，不依赖 parser fallback。按官方约束生成稳定 FMT rule IDs；质量提示使用 QLT rule IDs；现有 SEC001–SEC005 的含义和严重级别保持兼容。

- [ ] **Step 6: 实现 CompositeSkillValidator 和工厂注入**

library 与 source 都通过同一个 composite validator。`GovernanceAnalyzer` 根据 root metadata 计算真实 Skill 目录，不再把相对路径父目录当作可扫描根目录。findings 以 `(skill_id, rule_id, evidence_path, message)` 稳定去重。

- [ ] **Step 7: 收紧 SkillSpector 子进程边界**

命令只能来自配置；继续使用参数数组、`stdin=DEVNULL`、timeout 和 JSON 输出，不允许 shell。适配器异常不得包含秘密内容或完整 stdout/stderr。

- [ ] **Step 8: 运行规范、安全和来源回归**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/test_validators.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/security -q
```

- [ ] **Step 9: 提交 Task 8**

```powershell
git add src/skillcheck/core/validation.py src/skillcheck/core/validators.py src/skillcheck/core/parser.py src/skillcheck/skillspector.py src/skillcheck/governance/analyzer.py src/skillcheck/app/context.py src/skillcheck/mcp/tools.py tests/test_validators.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/security
git commit -m "feat: unify skill specification and security validation"
```

---

### Task 9: 完成 MCP/报告兼容、验收旅程与文档

**解决的问题:** 前述单元改动需要通过真实 MCP、报告和完整目录流程证明能协同工作，并让使用者理解新字段与 scope 行为。

**Files:**
- Create: `tests/acceptance/test_governance_algorithm_p0_p1.py`
- Modify: `src/skillcheck/mcp/instructions.py`
- Modify: `src/skillcheck/governance/reports.py`
- Modify: `README.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/review-and-privacy.md`
- Modify: `docs/troubleshooting.md`
- Test: `tests/mcp/test_contract.py`
- Test: `tests/governance/test_reports.py`
- Test: `tests/acceptance/test_governance_algorithm_p0_p1.py`

**Interfaces:**
- Preserves: 四个 MCP tool names 和保存确认语义。
- Documents: `skill_findings`、pair evidence、相似度统计、scope 值、embedding 签名和可选 SkillSpector。

- [ ] **Step 1: 编写跨入口验收测试**

验收测试在隔离 `SKILLCHECK_HOME` 中完成：

1. 创建 global、当前 project、其他 project Skill；
2. 初始化并通过 MCP runtime 同步；
3. 修改一个 Skill，验证新 snapshot 有当前签名向量；
4. 运行 project scope，验证没有其他项目 Skill；
5. 生成一个独立安全 finding、一个中文 overlap pair 和 A-B-C 链式 pair；
6. 验证 findings 与 groups 分离、中文 pair 可取证、A-B-C 不误合并；
7. 保存 review 时仍需显式调用，且不会修改 Skill 文件。

- [ ] **Step 2: 增加 168 Skill 宽松性能门禁**

使用短 Skill、默认 hash backend，断言完整分析在 30 秒内结束、`skills_considered == 168`。此测试只防止死循环和意外高阶退化，不作为算法微基准。

- [ ] **Step 3: 更新 MCP 和报告兼容测试**

断言工具名仍为四个；`skillcheck_analyze` 返回新增字段但旧字段仍存在；`skillcheck_evidence` 返回 pair evidence 时正文仍脱敏、分页仍为零基输入；报告按 skill ID 展示 findings。

- [ ] **Step 4: 更新用户文档**

明确：

- scope 四个取值及 source 模式语义；
- `top_k` 是邻居数，不是参与分析数；
- `content_hash` 与 `instruction_hash` 的区别；
- 相似度统计和成对证据；
- 内建安全始终运行，SkillSpector 仅在配置后运行；
- 当前 Agent 仍是语义终审者。

- [ ] **Step 5: 运行验收测试**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/acceptance/test_governance_algorithm_p0_p1.py tests/mcp tests/governance/test_reports.py -q
```

- [ ] **Step 6: 运行完整质量门禁**

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
python -m ruff check src tests
python -m build --no-isolation
```

Expected: 测试全部通过、Ruff 输出 `All checks passed!`、wheel 与 sdist 构建成功。构建不下载可选 embedding 或 SkillSpector。

- [ ] **Step 7: 检查工作树和安全边界**

```powershell
git diff --check
git status --short
```

人工确认测试只写临时目录，没有修改真实 `~/.codex`、`~/.claude`、`~/.cursor` 或用户 Skill。

- [ ] **Step 8: 提交 Task 9**

```powershell
git add tests/acceptance/test_governance_algorithm_p0_p1.py src/skillcheck/mcp/instructions.py src/skillcheck/governance/reports.py README.md docs/getting-started.md docs/review-and-privacy.md docs/troubleshooting.md tests/mcp/test_contract.py tests/governance/test_reports.py
git commit -m "docs: describe governance algorithm p0 p1 behavior"
```

---

## 计划自检

- P0 配置真实生效：Task 1。
- P0 MCP/增量向量与模型选择：Task 2。
- P0 scope 和完整输入：Task 3。
- P0 风险/关系分离与 conflict threshold：Task 4。
- P0 链式聚类和相似度语义：Task 5。
- P1 package/instruction 双哈希和官方字段：Task 6。
- P1 中文/英文/混合候选召回：Task 7。
- P1 库与来源统一校验、可选 SkillSpector：Task 8。
- MCP、报告、隐私和真实旅程：Task 9。
- 五项 Review Focus 均有明确归属测试。
- 新旧接口名称在任务间一致；Task 4 的 `PairSignals` 被 Task 5、7 复用。
- 计划不包含 P2 训练与指标闭环，也不要求新增必装模型。
