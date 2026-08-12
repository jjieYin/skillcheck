# Skillcheck v0.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 Skillcheck v0.5：提供 CodeGraph 风格的 Agent 多选安装、按治理作用域区分真正重复和跨 Agent 镜像副本、只监测的同步组，以及不会在普通任务中误触发的 MCP 指令契约。

**Architecture:** 在现有 SQLite 目录上增加可迁移的 v5 Schema，用独立的作用域分类器和同步组服务扩展治理分析；MCP 只暴露分析、取证、保存复核和保存同步组四个受控工具。CLI 通过专用交互层处理 Agent 多选和同步组管理，任何 Skill 文件变更仍由既有预览、确认、哈希和原子写入边界控制。

**Tech Stack:** Python 3.11、Typer、Pydantic v2、SQLite/FTS5、NumPy、FastMCP、Questionary/prompt_toolkit、PyInstaller、pytest、ruff。

---

## 0. 实施约束与文件结构

本计划按依赖顺序执行。每个 Task 必须独立完成测试、代码审查和提交，再进入下一项。不得把多个 Task 合并成一次大提交。

新增文件职责：

- `src/skillcheck/catalog/migrations.py`：只负责 v4 → v5 数据库迁移；
- `src/skillcheck/governance/scopes.py`：只负责治理空间键和完全重复/镜像副本分类；
- `src/skillcheck/governance/sync_groups.py`：只负责同步组创建、校验和状态计算；
- `src/skillcheck/ui/agent_picker.py`：只负责跨平台 Agent 多选，不写配置；
- `src/skillcheck/commands/groups.py`：同步组 CLI 入口，不直接操作 SQL；
- `scripts/verify_trigger_policy.py`：可选真实 Agent 触发边界验收器；
- `tests/fixtures/scopes/`：跨 Agent、同作用域和漂移场景测试数据。

修改文件职责保持不变：

- `catalog/schema.sql` 和 `catalog/database.py` 管理 Schema；
- `governance/analyzer.py` 组装分析结果；
- `governance/repository.py` 负责分析运行的持久化；
- `mcp/tools.py` 和 `mcp/server.py` 暴露受控 JSON 契约；
- `commands/install.py` 只编排安装交互和现有 InstallPipeline；
- `install.ps1` / `install.sh` 只安装发布包并在交互终端进入向导。

---

### Task 1: 建立可保留 v0.4 数据的 v5 Catalog Schema

**Files:**
- Create: `src/skillcheck/catalog/migrations.py`
- Modify: `src/skillcheck/catalog/schema.sql`
- Modify: `src/skillcheck/catalog/database.py`
- Test: `tests/catalog/test_schema.py`
- Test: `tests/catalog/test_migrations.py`

- [ ] **Step 1: 编写 v5 新库和 v4 迁移失败测试**

在 `tests/catalog/test_migrations.py` 写入：

```python
from skillcheck.catalog.database import CatalogDatabase


def test_v4_catalog_migrates_to_v5_without_losing_skills(v4_catalog) -> None:
    database = CatalogDatabase(v4_catalog)

    database.initialize()

    assert database.schema_version() == 5
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sync_groups").fetchone()[0] == 0


def test_migration_rolls_back_when_v5_table_creation_fails(v4_catalog, monkeypatch) -> None:
    monkeypatch.setattr(
        "skillcheck.catalog.migrations.V4_TO_V5_SQL",
        "CREATE TABLE sync_groups(group_id TEXT); INVALID SQL",
    )

    with pytest.raises(IncompatibleCatalogError):
        CatalogDatabase(v4_catalog).initialize()

    with sqlite3.connect(v4_catalog) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "4"
```

在 `tests/catalog/test_schema.py` 把期望表扩展为 `sync_groups`、`sync_group_members`，并断言 Schema 版本为 5。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/catalog/test_schema.py tests/catalog/test_migrations.py -q`

Expected: FAIL，提示版本仍为 4，且 `sync_groups` 不存在。

- [ ] **Step 3: 定义 v5 Schema 和迁移事务**

把 `schema.sql` 的版本改为 `5`，并加入：

```sql
CREATE TABLE sync_groups (
    group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    authority_skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    policy TEXT NOT NULL CHECK(policy = 'monitor_only'),
    baseline_revision TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sync_group_members (
    group_id TEXT NOT NULL REFERENCES sync_groups(group_id) ON DELETE CASCADE,
    skill_id TEXT NOT NULL REFERENCES skills(skill_id),
    role TEXT NOT NULL CHECK(role IN ('authority', 'mirror')),
    baseline_snapshot_id TEXT NOT NULL REFERENCES skill_snapshots(snapshot_id),
    baseline_content_hash TEXT NOT NULL,
    PRIMARY KEY(group_id, skill_id),
    UNIQUE(skill_id)
);

CREATE INDEX idx_sync_group_members_skill ON sync_group_members(skill_id);
```

在 `migrations.py` 定义完整、无占位符的 `V4_TO_V5_SQL`，最后一条语句更新 `schema_meta`。在 `CatalogDatabase.initialize()` 中只允许 `4 → 5`，整段迁移必须位于 `BEGIN IMMEDIATE` / rollback / commit 内。

- [ ] **Step 4: 更新完整结构校验**

在 `database.py` 中：

```python
schema_version_number = 5
```

同步更新 `_expected_tables()`、`_expected_schema_objects()` 和 `_expected_columns()`，让迁移后的数据库与新建数据库通过同一套精确结构检查。

- [ ] **Step 5: 运行 Schema 测试**

Run: `python -m pytest tests/catalog/test_schema.py tests/catalog/test_migrations.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/catalog/schema.sql src/skillcheck/catalog/database.py src/skillcheck/catalog/migrations.py tests/catalog/test_schema.py tests/catalog/test_migrations.py
git commit -m "feat: migrate catalogs to v5 sync-group schema"
```

---

### Task 2: 定义同步组领域模型与持久化仓库

**Files:**
- Modify: `src/skillcheck/governance/models.py`
- Create: `src/skillcheck/governance/sync_groups.py`
- Modify: `src/skillcheck/governance/repository.py`
- Test: `tests/governance/test_sync_groups.py`

- [ ] **Step 1: 编写模型、唯一成员和删除安全测试**

```python
def test_create_sync_group_persists_authority_and_mirrors(catalog_with_three_agents) -> None:
    service = SyncGroupService(catalog_with_three_agents.repository)
    created = service.create(
        name="api-review",
        authority_skill_id="codex-api",
        member_skill_ids=["claude-api", "cursor-api"],
        baseline_revision="sync-1",
    )
    assert created.policy is SyncPolicy.MONITOR_ONLY
    assert [member.role for member in created.members] == [
        SyncMemberRole.AUTHORITY,
        SyncMemberRole.MIRROR,
        SyncMemberRole.MIRROR,
    ]


def test_one_skill_cannot_belong_to_two_sync_groups(catalog_with_three_agents) -> None:
    service = SyncGroupService(catalog_with_three_agents.repository)
    service.create("first", "codex-api", ["claude-api"], "sync-1")
    with pytest.raises(ValueError, match="already belongs"):
        service.create("second", "cursor-api", ["claude-api"], "sync-1")


def test_remove_group_does_not_delete_skills(catalog_with_three_agents) -> None:
    service = SyncGroupService(catalog_with_three_agents.repository)
    group = service.create("api", "codex-api", ["claude-api"], "sync-1")
    service.remove(group.group_id)
    assert catalog_with_three_agents.repository.get_current_skill("codex-api") is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/governance/test_sync_groups.py -q`

Expected: FAIL，模型和服务尚不存在。

- [ ] **Step 3: 实现领域模型**

在 `governance/models.py` 增加：

```python
class SyncPolicy(StrEnum):
    MONITOR_ONLY = "monitor_only"


class SyncMemberRole(StrEnum):
    AUTHORITY = "authority"
    MIRROR = "mirror"


class SyncGroupStatus(StrEnum):
    IN_SYNC = "IN_SYNC"
    DRIFTED = "DRIFTED"
    DIVERGED = "DIVERGED"
    BROKEN = "BROKEN"
    INVALID_MEMBER = "INVALID_MEMBER"


class SyncGroupMember(BaseModel):
    skill_id: str
    role: SyncMemberRole
    baseline_snapshot_id: str
    baseline_content_hash: str


class SyncGroup(BaseModel):
    group_id: str
    name: str
    authority_skill_id: str
    policy: SyncPolicy = SyncPolicy.MONITOR_ONLY
    baseline_revision: str
    status: SyncGroupStatus
    members: list[SyncGroupMember]
```

- [ ] **Step 4: 实现仓库事务与服务校验**

在 `GovernanceRepository` 增加 `insert_sync_group()`、`get_sync_group()`、`list_sync_groups()`、`delete_sync_group()`。`SyncGroupService.create()` 必须验证：成员至少两个、权威源包含在组内、所有 Skill 当前为 active、Skill 尚未属于其他组，并在一次事务中保存组和成员基线。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest tests/governance/test_sync_groups.py tests/governance/test_analyzer.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/governance/models.py src/skillcheck/governance/sync_groups.py src/skillcheck/governance/repository.py tests/governance/test_sync_groups.py
git commit -m "feat: persist monitor-only sync groups"
```

---

### Task 3: 实现治理作用域与 EXACT_DUPLICATE / MIRRORED_COPY 分类

**Files:**
- Create: `src/skillcheck/governance/scopes.py`
- Modify: `src/skillcheck/governance/models.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Test: `tests/governance/test_scopes.py`
- Test fixtures: `tests/fixtures/scopes/`

- [ ] **Step 1: 编写作用域分类测试**

```python
def test_same_root_same_hash_is_exact_duplicate(scope_fixture) -> None:
    groups = ScopeClassifier(scope_fixture.roots).classify(scope_fixture.same_root_copies)
    assert [(group.relation, group.member_skill_ids) for group in groups] == [
        (Relation.EXACT_DUPLICATE, ["codex-copy-a", "codex-copy-b"])
    ]


def test_same_hash_across_agents_is_mirrored_copy(scope_fixture) -> None:
    groups = ScopeClassifier(scope_fixture.roots).classify(scope_fixture.cross_agent_copies)
    assert groups[0].relation is Relation.MIRRORED_COPY
    assert groups[0].requires_agent_judgment is False


def test_similar_but_non_identical_cross_agent_skills_are_not_auto_mirrors(scope_fixture) -> None:
    groups = ScopeClassifier(scope_fixture.roots).classify(scope_fixture.similar_cross_agent)
    assert all(group.relation is not Relation.MIRRORED_COPY for group in groups)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/governance/test_scopes.py -q`

Expected: FAIL，`ScopeClassifier` 和 `MIRRORED_COPY` 尚不存在。

- [ ] **Step 3: 实现稳定作用域键**

```python
@dataclass(frozen=True, order=True)
class GovernanceScopeKey:
    provider: str
    scope: str
    project_path: str
    root_id: str

    @classmethod
    def from_root(cls, root: LibraryRoot) -> "GovernanceScopeKey":
        return cls(
            provider=root.provider.casefold(),
            scope=root.scope.value,
            project_path=str(root.project_path.resolve()) if root.project_path else "",
            root_id=root.root_id,
        )
```

`ScopeClassifier.classify()` 先按 `content_hash` 分桶，再按 `GovernanceScopeKey` 分组：同一键内成员数大于 1 输出 `EXACT_DUPLICATE`；同一哈希跨两个及以上键输出一个 `MIRRORED_COPY`。

- [ ] **Step 4: 将分类接入分析器**

在 `Relation` 增加：

```python
MIRRORED_COPY = "MIRRORED_COPY"
SYNC_GROUP_DRIFT = "SYNC_GROUP_DRIFT"
```

`GovernanceAnalyzer._analyze()` 必须用 ScopeClassifier 生成精确重复和镜像组，并过滤 `LibraryAuditor` 原先不区分作用域的 `EXACT_DUPLICATE`，避免同一成员出现两次。

- [ ] **Step 5: 运行治理测试**

Run: `python -m pytest tests/governance/test_scopes.py tests/governance/test_analyzer.py tests/governance/test_evidence.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/governance/scopes.py src/skillcheck/governance/models.py src/skillcheck/governance/analyzer.py tests/governance/test_scopes.py tests/fixtures/scopes
git commit -m "feat: separate scoped duplicates from agent mirrors"
```

---

### Task 4: 计算同步组 IN_SYNC / DRIFTED / DIVERGED / BROKEN 状态

**Files:**
- Modify: `src/skillcheck/governance/sync_groups.py`
- Modify: `src/skillcheck/governance/repository.py`
- Test: `tests/governance/test_sync_group_status.py`

- [ ] **Step 1: 写五种状态测试**

```python
@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("all_equal", SyncGroupStatus.IN_SYNC),
        ("authority_changed_mirrors_unchanged", SyncGroupStatus.DRIFTED),
        ("mirror_changed_independently", SyncGroupStatus.DIVERGED),
        ("authority_missing", SyncGroupStatus.BROKEN),
        ("member_invalid", SyncGroupStatus.INVALID_MEMBER),
    ],
)
def test_sync_group_status(sync_group_scenario, scenario, expected) -> None:
    assert sync_group_scenario(scenario).status is expected
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/governance/test_sync_group_status.py -q`

Expected: FAIL，状态仍是创建时静态值。

- [ ] **Step 3: 实现确定性状态算法**

```python
def calculate_status(group: SyncGroup, current: dict[str, SkillSnapshot | None]) -> SyncGroupStatus:
    authority = current.get(group.authority_skill_id)
    if authority is None or authority.status is SkillStatus.MISSING:
        return SyncGroupStatus.BROKEN
    if any(item is None or item.status is SkillStatus.INVALID for item in current.values()):
        return SyncGroupStatus.INVALID_MEMBER
    if all(item.content_hash == authority.content_hash for item in current.values() if item):
        return SyncGroupStatus.IN_SYNC
    baseline = {member.skill_id: member.baseline_content_hash for member in group.members}
    authority_changed = authority.content_hash != baseline[group.authority_skill_id]
    mirror_changed = any(
        current[member.skill_id].content_hash != member.baseline_content_hash
        for member in group.members
        if member.role is SyncMemberRole.MIRROR and current.get(member.skill_id)
    )
    return SyncGroupStatus.DIVERGED if mirror_changed else (
        SyncGroupStatus.DRIFTED if authority_changed else SyncGroupStatus.DIVERGED
    )
```

- [ ] **Step 4: 刷新状态但不改变基线**

`SyncGroupService.get()` 和 `list()` 每次从当前快照计算状态，并只更新 `sync_groups.status/updated_at`。不得自动修改成员基线；只有未来显式“接受新基线”的功能才能修改基线，本期不实现。

- [ ] **Step 5: 运行测试**

Run: `python -m pytest tests/governance/test_sync_group_status.py tests/governance/test_sync_groups.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/governance/sync_groups.py src/skillcheck/governance/repository.py tests/governance/test_sync_group_status.py
git commit -m "feat: detect sync-group drift and divergence"
```

---

### Task 5: 扩展分析摘要、证据和报告

**Files:**
- Modify: `src/skillcheck/governance/models.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/governance/repository.py`
- Modify: `src/skillcheck/models/audit.py`
- Modify: `src/skillcheck/pipelines/scan_pipeline.py`
- Modify: `src/skillcheck/reports/writer.py`
- Test: `tests/governance/test_evidence.py`
- Test: `tests/governance/test_reports.py`
- Test: `tests/commands/test_scan.py`

- [ ] **Step 1: 编写摘要和证据失败测试**

```python
def test_analysis_counts_mirrors_separately_from_duplicates(analyzer) -> None:
    result = analyzer.analyze_library(limit=None)
    assert result.summary.exact_duplicates == 1
    assert result.summary.mirrored_copy_groups == 2
    assert result.summary.sync_groups_drifted == 1


def test_mirror_evidence_includes_agent_scope_and_snapshot(analyzer) -> None:
    result = analyzer.analyze_library(limit=None)
    mirror = next(group for group in result.groups if group.relation is Relation.MIRRORED_COPY)
    evidence = analyzer.evidence(result.run_id, mirror.group_id, include_body=False)
    assert evidence.members[0].provider == "codex"
    assert evidence.members[0].scope == "global"
    assert evidence.members[0].snapshot_id
    assert evidence.members[0].root_path
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/governance/test_evidence.py tests/governance/test_reports.py tests/commands/test_scan.py -q`

Expected: FAIL，摘要与证据字段不存在。

- [ ] **Step 3: 扩展公开 JSON 模型**

```python
class AnalyzeSummary(BaseModel):
    skills_considered: int = 0
    exact_duplicates: int = 0
    mirrored_copy_groups: int = 0
    sync_groups_total: int = 0
    sync_groups_drifted: int = 0
    # 保留原有 overlap/conflict/variant/quality/security 字段


class EvidenceSkill(BaseModel):
    skill_id: str
    snapshot_id: str
    provider: str
    scope: str
    project_path: str | None
    root_path: str
    # 保留 name/description/hash/tools/.../body
```

从 `library_roots` 联表获取这些字段，不得从 Skill ID 字符串反推。

- [ ] **Step 4: 更新本地报告语义**

报告摘要必须分别显示：

```text
真正冗余：{exact_duplicates} 组
跨 Agent 镜像副本：{mirrored_copy_groups} 组（不计入冗余）
同步组：{sync_groups_total} 个
存在版本漂移：{sync_groups_drifted} 个
```

`MIRRORED_COPY` 的 recommendations 固定为“合理跨作用域分发；可选择建立只监测同步组”，不得出现删除或合并建议。

- [ ] **Step 5: 运行报告测试**

Run: `python -m pytest tests/governance/test_evidence.py tests/governance/test_reports.py tests/commands/test_scan.py -q`

Expected: PASS，并确认 JSON 中镜像数不计入 exact duplicate。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/governance/models.py src/skillcheck/governance/analyzer.py src/skillcheck/governance/repository.py src/skillcheck/models/audit.py src/skillcheck/pipelines/scan_pipeline.py src/skillcheck/reports/writer.py tests/governance/test_evidence.py tests/governance/test_reports.py tests/commands/test_scan.py
git commit -m "feat: report mirrors and sync drift separately"
```

---

### Task 6: 新增保存同步组的 MCP 工具

**Files:**
- Modify: `src/skillcheck/mcp/tools.py`
- Modify: `src/skillcheck/mcp/server.py`
- Modify: `src/skillcheck/governance/sync_groups.py`
- Test: `tests/mcp/test_contract.py`
- Test: `tests/mcp/test_server.py`
- Test: `tests/mcp/test_tools.py`

- [ ] **Step 1: 编写四工具契约和 stale 拒绝测试**

```python
EXPECTED_TOOLS = {
    "skillcheck_analyze",
    "skillcheck_evidence",
    "skillcheck_save_review",
    "skillcheck_save_sync_group",
}


def test_save_sync_group_rejects_stale_analysis(mcp_tools, stale_mirror_run) -> None:
    with pytest.raises(StaleAnalysisError):
        mcp_tools.save_sync_group(
            run_id=stale_mirror_run.run_id,
            group_id=stale_mirror_run.group_id,
            name="api-review",
            authority_skill_id="codex-api",
            member_skill_ids=["claude-api"],
            policy="monitor_only",
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/mcp/test_contract.py tests/mcp/test_server.py tests/mcp/test_tools.py -q`

Expected: FAIL，只有三个工具。

- [ ] **Step 3: 实现 MCP facade 校验**

`SkillcheckMcpTools.save_sync_group()` 必须：验证 run/group 存在且关系为 `MIRRORED_COPY`；成员集合与候选一致；authority 在成员内；policy 只能为 `monitor_only`；当前 revision 和 snapshot 与分析运行一致，然后调用 `SyncGroupService.create()`。

- [ ] **Step 4: 注册工具和精确 Schema**

```python
@server.tool(
    name="skillcheck_save_sync_group",
    description="Save a user-confirmed monitor-only group for cross-Agent mirrored Skills; never copies or edits Skill files.",
)
def skillcheck_save_sync_group(
    run_id: str,
    group_id: str,
    name: str,
    authority_skill_id: str,
    member_skill_ids: list[str],
    policy: str = "monitor_only",
) -> dict[str, object]:
    return tools.save_sync_group(
        run_id, group_id, name, authority_skill_id, member_skill_ids, policy
    )
```

- [ ] **Step 5: 运行 MCP 测试**

Run: `python -m pytest tests/mcp -q`

Expected: PASS，工具集合精确为四个。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/mcp/tools.py src/skillcheck/mcp/server.py src/skillcheck/governance/sync_groups.py tests/mcp/test_contract.py tests/mcp/test_server.py tests/mcp/test_tools.py
git commit -m "feat: save user-confirmed sync groups through MCP"
```

---

### Task 7: 修复 MCP 无关任务误触发并记录触发来源

**Files:**
- Modify: `src/skillcheck/mcp/instructions.py`
- Modify: `src/skillcheck/mcp/server.py`
- Modify: `src/skillcheck/mcp/tools.py`
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/governance/repository.py`
- Test: `tests/mcp/test_trigger_policy.py`
- Test: `tests/governance/test_analyzer.py`

- [ ] **Step 1: 编写指令正反边界测试**

```python
def test_instructions_are_conditional_and_exclude_ordinary_work() -> None:
    assert "Only use Skillcheck when" in MCP_INSTRUCTIONS
    assert "Do not call Skillcheck for ordinary coding" in MCP_INSTRUCTIONS
    assert "If no candidate groups are returned" in MCP_INSTRUCTIONS
    assert "Do not call skillcheck_evidence" in MCP_INSTRUCTIONS


def test_analyze_records_trigger_source(analyzer, repository) -> None:
    result = analyzer.analyze_library(limit=20, trigger_source="explicit_user")
    assert repository.analysis_parameters(result.run_id)["trigger_source"] == "explicit_user"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/mcp/test_trigger_policy.py tests/governance/test_analyzer.py -q`

Expected: FAIL，旧文案仍是无条件 `Use it in this order`。

- [ ] **Step 3: 替换 Agent/MCP 指令**

`MCP_INSTRUCTIONS` 使用完整条件式文案：

```text
Only use Skillcheck when the user's request concerns local Skill inventory,
duplication, overlap, conflicts, installation preflight, cross-Agent mirrors,
sync groups, or Skill governance.

Do not call Skillcheck for ordinary coding, debugging, testing, writing,
repository exploration, or tasks that merely use an already-selected Skill.

For a relevant request, call skillcheck_analyze first. If no candidate groups
are returned, stop: do not call skillcheck_evidence and do not save an empty
review. Otherwise read bounded evidence, explain the decision, and save only
when the user asked for a persisted review or confirmed a sync group.
```

- [ ] **Step 4: 强化每个工具描述**

`skillcheck_analyze` 的描述必须包含 `Use only for local Skill governance or incoming Skill preflight; not for ordinary software-development tasks.`；其余三个工具明确写为分析后的后续工具，避免 Agent 把它们当入口。

- [ ] **Step 5: 保存 trigger_source**

为 MCP `skillcheck_analyze` 增加：

```python
trigger_source: Literal["explicit_user", "agent_intent", "tool_chain"] = "agent_intent"
```

CLI `scan` 内部使用 `cli`，因此 Analyzer 内部类型允许 `cli`；把值写入 `analysis_runs.parameters_json`，不得记录完整用户提示词。

- [ ] **Step 6: 运行测试**

Run: `python -m pytest tests/mcp/test_trigger_policy.py tests/mcp/test_contract.py tests/governance/test_analyzer.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/skillcheck/mcp/instructions.py src/skillcheck/mcp/server.py src/skillcheck/mcp/tools.py src/skillcheck/governance/analyzer.py src/skillcheck/governance/repository.py tests/mcp/test_trigger_policy.py tests/governance/test_analyzer.py
git commit -m "fix: constrain Skillcheck MCP activation to governance tasks"
```

---

### Task 8: 提供同步组 CLI 管理入口

**Files:**
- Create: `src/skillcheck/commands/groups.py`
- Modify: `src/skillcheck/app/main.py`
- Modify: `src/skillcheck/app/context.py`
- Test: `tests/commands/test_groups.py`

- [ ] **Step 1: 编写 list/show/remove 和取消创建测试**

```python
def test_groups_list_shows_status(runner, configured_groups) -> None:
    result = runner.invoke(app, ["groups", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["status"] == "DRIFTED"


def test_groups_remove_deletes_only_metadata(runner, configured_groups) -> None:
    result = runner.invoke(app, ["groups", "remove", "group-api", "--yes"])
    assert result.exit_code == 0
    assert configured_groups.catalog.get_current_skill("codex-api") is not None


def test_groups_create_cancel_is_read_only(runner, mirror_candidate) -> None:
    result = runner.invoke(app, ["groups", "create"], input="n\n")
    assert result.exit_code == 0
    assert mirror_candidate.repository.list_sync_groups() == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/commands/test_groups.py -q`

Expected: FAIL，命令不存在。

- [ ] **Step 3: 实现 Typer 子应用**

```python
groups_app = typer.Typer(help="Inspect cross-Agent mirrors and monitor-only sync groups.")

@groups_app.command("list")
def list_groups(as_json: bool = typer.Option(False, "--json")) -> None: ...

@groups_app.command("show")
def show_group(group_id: str, as_json: bool = typer.Option(False, "--json")) -> None: ...

@groups_app.command("remove")
def remove_group(group_id: str, yes: bool = typer.Option(False, "--yes")) -> None: ...

@groups_app.command("create")
def create_group(
    run_id: str | None = typer.Option(None),
    candidate: str | None = typer.Option(None),
    authority: str | None = typer.Option(None),
    yes: bool = typer.Option(False, "--yes"),
) -> None: ...
```

无参数 `skillcheck groups` 显示交互菜单；非 TTY 环境必须要求显式子命令。创建流程复用分析候选和 `SyncGroupService`，不得复制文件。

- [ ] **Step 4: 注册命令并运行测试**

Run: `python -m pytest tests/commands/test_groups.py tests/app/test_main.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/skillcheck/commands/groups.py src/skillcheck/app/main.py src/skillcheck/app/context.py tests/commands/test_groups.py
git commit -m "feat: add monitor-only sync group CLI"
```

---

### Task 9: 实现 CodeGraph 风格的 Agent 多选组件

**Files:**
- Create: `src/skillcheck/ui/__init__.py`
- Create: `src/skillcheck/ui/agent_picker.py`
- Modify: `pyproject.toml`
- Modify: `skillcheck.spec`
- Test: `tests/ui/test_agent_picker.py`

- [ ] **Step 1: 编写选择、取消和默认值测试**

```python
def test_detected_and_configured_agents_are_preselected() -> None:
    model = build_picker_model(
        detections=[detected("codex"), detected("claude"), missing("cursor")],
        configured=["codex"],
    )
    assert [item.value for item in model if item.checked] == ["codex", "claude"]
    assert model[2].label.endswith("（未检测）")


def test_escape_returns_cancelled_without_selection(fake_prompt) -> None:
    fake_prompt.answer = None
    result = AgentPicker(prompt=fake_prompt).choose([])
    assert result.cancelled is True
    assert result.selected == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/ui/test_agent_picker.py -q`

Expected: FAIL，UI 模块不存在。

- [ ] **Step 3: 添加依赖和纯模型层**

在 `pyproject.toml` 增加：

```toml
"questionary>=2.1,<3",
```

定义：

```python
@dataclass(frozen=True)
class PickerItem:
    value: str
    label: str
    checked: bool
    available: bool

@dataclass(frozen=True)
class PickerResult:
    selected: list[str]
    cancelled: bool = False
```

模型构造与终端渲染分离，使测试不依赖真实按键。

- [ ] **Step 4: 实现 Questionary 适配器**

使用 `questionary.checkbox()`，提示中明确 `↑/↓`、Space、Enter、Esc；`None` 统一转换成 `cancelled=True`。未检测 Agent 允许显示但默认不选中；选择后仍由安装预览和二次确认把关。

- [ ] **Step 5: 验证 PyInstaller 收集**

在 `skillcheck.spec` 显式收集 `questionary` 和 `prompt_toolkit` 子模块，运行：

Run: `python scripts/build_release.py --version 0.5.0-dev --platform windows --arch x64`

Expected: 构建成功，生成的 `skillcheck.exe version` 可运行。

- [ ] **Step 6: 提交**

```bash
git add pyproject.toml skillcheck.spec src/skillcheck/ui tests/ui/test_agent_picker.py
git commit -m "feat: add cross-platform Agent checkbox picker"
```

---

### Task 10: 将多选组件接入 install，同时保留非交互兼容

**Files:**
- Modify: `src/skillcheck/commands/install.py`
- Modify: `src/skillcheck/commands/uninstall.py`
- Modify: `src/skillcheck/lifecycle/uninstall.py`
- Test: `tests/commands/test_install_command.py`
- Test: `tests/commands/test_uninstall.py`

- [ ] **Step 1: 编写交互选择和单 Agent 移除测试**

```python
def test_interactive_install_uses_picker(monkeypatch, picker, pipeline) -> None:
    picker.result = PickerResult(["codex", "claude"])
    result = runner.invoke(app, ["install"], input="y\n")
    assert result.exit_code == 0
    assert pipeline.previewed_agents == ["codex", "claude"]


def test_picker_cancel_does_not_write(monkeypatch, picker, pipeline) -> None:
    picker.result = PickerResult([], cancelled=True)
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0
    assert pipeline.applied is False


def test_uninstall_target_removes_only_selected_agent(configured_targets) -> None:
    result = runner.invoke(app, ["uninstall", "--target", "cursor", "--yes"])
    assert result.exit_code == 0
    assert configured_targets.codex_mcp.exists()
    assert not configured_targets.cursor_mcp_marker_exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/commands/test_install_command.py tests/commands/test_uninstall.py -q`

Expected: FAIL，install 仍使用逗号 prompt，uninstall 无 `--target`。

- [ ] **Step 3: 接入选择决策表**

```python
if target != "auto" or yes or not sys.stdin.isatty():
    selected = _selected_targets(pipeline, target)
else:
    picker_result = AgentPicker().choose(
        pipeline.discover().agents,
        configured=loaded.targets.configured,
    )
    if picker_result.cancelled:
        typer.echo("Cancelled; no files were changed.")
        return
    selected = picker_result.selected
```

`--target ... --yes` 的行为必须保持稳定。取消选中只影响本次新增目标，不移除已配置 Agent。

- [ ] **Step 4: 实现精确卸载目标**

`skillcheck uninstall --target cursor --yes` 只调用 Cursor target 的标记块和 MCP 配置移除，并从 `config.targets.configured` 删除 cursor。不得删除用户 Skills、其他 Agent 配置、目录数据库或 CLI。

- [ ] **Step 5: 运行命令测试**

Run: `python -m pytest tests/commands/test_install_command.py tests/commands/test_uninstall.py tests/lifecycle/test_uninstall.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/skillcheck/commands/install.py src/skillcheck/commands/uninstall.py src/skillcheck/lifecycle/uninstall.py tests/commands/test_install_command.py tests/commands/test_uninstall.py
git commit -m "feat: install and remove selected Agent integrations"
```

---

### Task 11: 统一 Windows/macOS/Linux 首次安装流程

**Files:**
- Modify: `install.ps1`
- Modify: `install.sh`
- Modify: `tests/release/test_installer.ps1`
- Modify: `tests/release/test_install_sh.py`
- Test: `tests/release/test_install_entrypoints.py`

- [ ] **Step 1: 写交互和非交互脚本契约测试**

```python
def test_windows_installer_does_not_force_auto_yes() -> None:
    script = Path("install.ps1").read_text(encoding="utf-8")
    assert "install --target auto --yes" not in script
    assert "IsInputRedirected" in script


def test_posix_installer_enters_wizard_only_on_tty() -> None:
    script = Path("install.sh").read_text(encoding="utf-8")
    assert '[ -t 0 ] && [ -t 1 ]' in script
    assert '"${BIN}/skillcheck" install' in script
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/release/test_install_sh.py tests/release/test_install_entrypoints.py -q`

Expected: FAIL，Windows 仍无条件执行 auto/yes，POSIX 不进入向导。

- [ ] **Step 3: 修改安装脚本**

Windows：下载、校验、安装、PATH 和 smoke check 完成后，仅当 `[Environment]::UserInteractive -and -not [Console]::IsInputRedirected` 时运行 `& $executable install`；否则输出后续命令。

POSIX：安装 shim 后，仅当 `[ -t 0 ] && [ -t 1 ]` 时运行 `"${BIN}/skillcheck" install`；否则打印“Run skillcheck install in an interactive terminal”。

- [ ] **Step 4: 运行脚本测试**

Run: `python -m pytest tests/release/test_install_sh.py tests/release/test_install_entrypoints.py tests/release/test_assets.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add install.ps1 install.sh tests/release/test_installer.ps1 tests/release/test_install_sh.py tests/release/test_install_entrypoints.py
git commit -m "feat: launch Agent picker from interactive installers"
```

---

### Task 12: 建立真实 Agent 触发边界验收器

**Files:**
- Create: `scripts/verify_trigger_policy.py`
- Create: `tests/acceptance/trigger-policy-cases.json`
- Create: `tests/acceptance/test_trigger_policy_harness.py`
- Modify: `docs/agent-setup.md`

- [ ] **Step 1: 定义固定正反例数据**

`trigger-policy-cases.json` 必须包含：

```json
[
  {"id":"positive-duplicate","prompt":"检查本机 Skills 有没有重复","expect":"call"},
  {"id":"positive-preflight","prompt":"这个 GitHub Skill 安装前是否与现有能力冲突","expect":"call"},
  {"id":"positive-sync","prompt":"检查 Codex 和 Claude 的同步组是否漂移","expect":"call"},
  {"id":"negative-code","prompt":"写一个 Python 快速排序函数","expect":"no_call"},
  {"id":"negative-test","prompt":"修复这个单元测试","expect":"no_call"},
  {"id":"negative-readme","prompt":"帮我润色 README","expect":"no_call"},
  {"id":"negative-use-skill","prompt":"使用 api-review Skill 检查这个接口","expect":"no_call"},
  {"id":"negative-opt-out","prompt":"不要使用 Skillcheck，直接解释概念","expect":"no_call"}
]
```

- [ ] **Step 2: 编写 harness 单元测试**

```python
def test_harness_classifies_mcp_trace(tmp_path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"tool":"skillcheck_analyze"}\n', encoding="utf-8")
    assert observed_policy(trace) == "call"


def test_harness_rejects_evidence_after_empty_analysis(tmp_path) -> None:
    trace = write_trace(tmp_path, groups=[], next_tool=None, following="skillcheck_evidence")
    assert validate_trace(trace) == ["evidence called after empty analysis"]
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/acceptance/test_trigger_policy_harness.py -q`

Expected: FAIL，验收器不存在。

- [ ] **Step 4: 实现可插拔 Agent 命令验收器**

脚本参数：

```text
python scripts/verify_trigger_policy.py \
  --agent codex \
  --command "codex exec --json {prompt}" \
  --cases tests/acceptance/trigger-policy-cases.json \
  --output build/trigger-policy/codex.json
```

脚本只解析 Agent 的 JSON/事件输出中出现的 `skillcheck_*` 工具名，不保存完整模型思考；输出每个 case 的 observed、expected、pass 和工具序列。Claude/Cursor 使用各自可提供的非交互命令；若某 Agent 没有机器可读命令，则按 `docs/agent-setup.md` 的人工表格验收并附终端截图/日志摘要。

- [ ] **Step 5: 运行 harness 测试**

Run: `python -m pytest tests/acceptance/test_trigger_policy_harness.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add scripts/verify_trigger_policy.py tests/acceptance/trigger-policy-cases.json tests/acceptance/test_trigger_policy_harness.py docs/agent-setup.md
git commit -m "test: add Agent trigger policy acceptance harness"
```

---

### Task 13: 完成 v0.5 端到端验收、文档和发布准备

**Files:**
- Modify: `README.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/agent-setup.md`
- Modify: `docs/review-and-privacy.md`
- Modify: `docs/release-checklist.md`
- Modify: `src/skillcheck/__init__.py`
- Modify: `pyproject.toml`
- Modify: `scripts/render_manifest.py`
- Modify: `tests/test_version.py`
- Modify: `tests/release/test_manifest.py`
- Modify: `.github/workflows/release.yml`
- Test: `tests/acceptance/test_v5_user_journey.py`

- [ ] **Step 1: 编写完整用户旅程测试**

```python
def test_v5_first_run_mirror_and_sync_group_journey(v5_cli) -> None:
    v5_cli.install_agents(["codex", "claude"])
    initialized = v5_cli.init_catalog()
    assert initialized.skill_count >= 2

    analysis = v5_cli.analyze_library()
    mirror = next(group for group in analysis.groups if group.relation == "MIRRORED_COPY")
    created = v5_cli.save_sync_group(analysis.run_id, mirror.group_id, authority="codex-api")
    assert created.status == "IN_SYNC"

    v5_cli.modify_authority()
    assert v5_cli.groups_list()[0]["status"] == "DRIFTED"
    assert v5_cli.skill_files_unchanged_except_fixture_edit()
```

- [ ] **Step 2: 运行测试确认失败或定位剩余集成缺口**

Run: `python -m pytest tests/acceptance/test_v5_user_journey.py -q`

Expected: 首次运行时允许因尚未接通的接口失败；修复只能落在本 Task 的集成胶水和文档，不得重写前面已审查的领域算法。

- [ ] **Step 3: 更新用户文档**

README 和 getting-started 必须以以下流程为主：安装 → 多选 Agent → init → 在 Agent 中提出治理请求。明确普通任务不会调用 Skillcheck；解释 `MIRRORED_COPY` 不等于冗余；说明同步组只监测、不自动覆盖。

- [ ] **Step 4: 更新版本和发布清单**

```python
__version__ = "0.5.0"
```

`pyproject.toml` 同步为 `0.5.0`；manifest 使用 `data_schema_version: 5` 和 `minimum_compatible_version: 0.5.0`；发布说明列明 v4 Catalog 会原地事务迁移，失败则保持 v4 不变。

- [ ] **Step 5: 运行全量质量门禁**

Run: `python -m pytest -q`

Expected: 全部通过，仅允许已记录的第三方 warning。

Run: `python -m ruff check src tests scripts`

Expected: PASS。

Run: `python -m build --no-isolation`

Expected: sdist 和 wheel 构建成功。

- [ ] **Step 6: 构建本机包并做 smoke test**

Windows Run:

```powershell
python scripts/build_release.py --version 0.5.0 --platform windows --arch x64
dist/skillcheck-0.5.0-windows-x64/skillcheck.exe version
dist/skillcheck-0.5.0-windows-x64/skillcheck.exe doctor --json
```

Expected: 版本显示 `skillcheck 0.5.0`；doctor 无 error；`serve --mcp` 启动 smoke 通过。

- [ ] **Step 7: 完成真实 Agent 正反例验收**

对已安装的 Codex、Claude Code、Cursor 分别执行 Task 12 的用例。发布门禁：正向调用率 100%，明确负向误调用率 0%，空候选后无 evidence/save_review。不可用 Agent 必须在 release checklist 中标明未验证，不得声称通过。

- [ ] **Step 8: 提交发布准备**

```bash
git add README.md docs src/skillcheck/__init__.py pyproject.toml scripts/render_manifest.py tests .github/workflows/release.yml
git commit -m "release: prepare skillcheck v0.5.0"
```

---

## 计划自检结果

- 需求一“Agent 多选”：Task 9、10、11、13 覆盖；
- 需求二“治理作用域”：Task 3、5、13 覆盖；
- 需求三“同步组”：Task 1、2、4、5、6、8、13 覆盖；
- 需求四“防误触发”：Task 7、12、13 覆盖；
- 安全边界：Task 2、6、8、10 的测试明确保证不修改或删除 Skill；
- v0.4 数据兼容：Task 1 使用事务迁移并验证失败回滚；
- 无 `TBD`、`TODO` 或未定义的“稍后实现”步骤；v0.5 不包含的自动同步能力被明确排除。

