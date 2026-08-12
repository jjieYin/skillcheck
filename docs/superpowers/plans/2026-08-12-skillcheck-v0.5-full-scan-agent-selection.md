# Skillcheck v0.5 Full Scan and Agent Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 发布 Skillcheck `v0.5.1`，使所有治理入口默认分析完整 Skill 集合，并让 Agent 多选向导记住上次结果、按本次选择精确增删 MCP 接入。

**Architecture:** 移除治理分析 API 中承担“截断输入集合”职责的 `limit`，让完整快照集合进入确定性查重和语义候选生成，同时继续对来源安全与证据输出分页。新增 Agent 选择状态和一次事务式 reconciliation 流程，把检测、选择、预览、应用、校验和持久化分离；本次选择是最终状态，取消选择只移除 Skillcheck 自己管理的 MCP 条目和指令块。

**Tech Stack:** Python 3.11、Typer、Questionary、Pydantic v2、SQLite、FastMCP、NumPy、pytest、Ruff、PyInstaller、GitHub Actions

---

## 0. 实施边界与文件职责

本计划继续使用现有 v5 Catalog Schema，不做数据库迁移。配置模型新增一个有默认值的字段，因此旧 `config.yaml` 可以直接加载。

文件职责：

- `governance/analyzer.py`：决定哪些 Skill 参与分析，不负责 MCP 参数兼容；
- `core/audit.py`：对完整 Skill 集合执行确定性和语义候选分析；
- `mcp/server.py`、`mcp/tools.py`：公开无数量截断的 MCP 契约；
- `ui/agent_picker.py`：只构建多选模型并返回选择，不写文件；
- `pipelines/install_pipeline.py`：计算并原子应用新增、保留、移除；
- `commands/install.py`：组织交互和显式非交互参数，保存精确选择；
- `targets/_mcp.py`、`targets/instructions.py`：生成安装与移除预览，不直接决定选择范围；
- `commands/status.py`、`commands/doctor.py`、`commands/uninstall.py`：消费同一份已确认选择，不自行推测全部 Agent。

当前工作树已经包含 MCP 默认全量分析的未提交修改。Task 1 必须先用测试固定目标行为，再整理这些修改；不得丢弃或覆盖用户现有改动。

---

### Task 1: 固定“所有 Skill 都参与分析”的领域契约

**Files:**
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/core/audit.py`
- Test: `tests/governance/test_analyzer.py`
- Test: `tests/governance/test_source_preflight.py`

- [ ] **Step 1: 编写超过 20 个 Skill 的本机库失败测试**

新增一个测试，创建 168 个快照，并把相同内容的两个 Skill 安排在稳定排序第 21 位以后：

```python
def test_default_library_analysis_considers_every_indexed_skill(catalog) -> None:
    for index in range(168):
        body = "duplicate tail" if index in {160, 167} else f"unique {index}"
        catalog.upsert_snapshot(make_snapshot(index, body))

    result = GovernanceAnalyzer(catalog).analyze_library()

    assert result.summary.skills_considered == 168
    assert any(
        group.relation is Relation.EXACT_DUPLICATE
        and set(group.member_skill_ids) == {"skill-160", "skill-167"}
        for group in result.groups
    )
```

- [ ] **Step 2: 编写超过 20 个 Skill 的来源预检失败测试**

```python
def test_source_preflight_considers_every_incoming_skill(analyzer, tmp_path) -> None:
    source = tmp_path / "source"
    for index in range(25):
        body = (
            "The leaked value is sk-abcdefghijklmnop."
            if index == 24
            else f"Safe implementation {index}."
        )
        write_skill(source / f"skill-{index:02d}", name=f"skill-{index:02d}", body=body)

    result = analyzer.analyze_source(source)

    assert result.summary.skills_considered == 25
    stored = analyzer.repository.get_source_preflight(result.run_id)
    assert any(item.rule_id == "SEC002" for item in stored.deterministic_blockers)
```

- [ ] **Step 3: 运行测试并确认旧实现失败**

Run:

```powershell
python -m pytest tests/governance/test_analyzer.py tests/governance/test_source_preflight.py -q
```

Expected: FAIL，旧实现只考虑前 20 个 Skill，或者 `analyze_source()` 仍要求/传递 `limit`。

- [ ] **Step 4: 移除领域层输入截断**

将公共入口改为：

```python
def analyze(
    self,
    mode: AnalyzeMode | str,
    *,
    source: Path | str | None = None,
    scope: str = "all",
    trigger_source: TriggerSource = "agent_intent",
) -> AnalyzeResult:
    selected_mode = AnalyzeMode(mode)
    if selected_mode is AnalyzeMode.LIBRARY:
        return self.analyze_library(scope=scope, trigger_source=trigger_source)
    if source is None:
        raise ValueError("source analysis requires a staged local directory or ZIP file")
    return self.analyze_source(source, scope=scope, trigger_source=trigger_source)
```

`analyze_library()` 和 `analyze_source()` 都把完整快照列表交给 `_analyze()`。删除 `_select_snapshots()` 的切片职责和 `_validate_limit()`；来源安全仍由 `SourceLimits` 负责。

- [ ] **Step 5: 把候选邻居数量与 Skill 总数分离**

在 `_analyze()` 中明确使用完整集合：

```python
records = [self._record(item) for item in snapshots]
findings = {item.skill_id: _snapshot_findings(item) for item in snapshots}
vectors = self._vectors_for(snapshots, lexical_fallback=lexical_fallback)
candidate_neighbors = max(1, len(snapshots) - 1)
audit = LibraryAuditor(top_k=candidate_neighbors).audit(records, vectors, findings=findings)
```

这样所有 Skill 都参与规则、哈希和语义比较。证据分页 `_PAGE_SIZE` 保持不变，它只控制返回数据量。

- [ ] **Step 6: 运行领域与来源测试**

Run:

```powershell
python -m pytest tests/governance/test_analyzer.py tests/governance/test_source_preflight.py tests/governance/test_evidence.py -q
```

Expected: PASS，`skills_considered` 等于完整输入数量，尾部重复项能够被发现。

- [ ] **Step 7: 提交 Task 1**

```powershell
git add src/skillcheck/governance/analyzer.py src/skillcheck/core/audit.py tests/governance/test_analyzer.py tests/governance/test_source_preflight.py
git commit -m "fix: analyze complete skill collections"
```

---

### Task 2: 从 MCP 契约移除分析数量限制

**Files:**
- Modify: `src/skillcheck/mcp/server.py`
- Modify: `src/skillcheck/mcp/tools.py`
- Modify: `src/skillcheck/mcp/instructions.py`
- Test: `tests/mcp/test_tools.py`
- Test: `tests/mcp/test_server.py`
- Test: `tests/mcp/test_contract.py`

- [ ] **Step 1: 编写 MCP Schema 和调用失败测试**

```python
def test_analyze_tool_schema_has_no_limit_parameter(server) -> None:
    schema = tool_schema(server, "skillcheck_analyze")
    assert "limit" not in schema["inputSchema"]["properties"]


def test_mcp_library_analysis_passes_no_count_cap() -> None:
    tools, analyzer, _, calls = _tools()

    tools.analyze("library")

    assert calls == ["before_query"]
    assert analyzer.calls == [("analyze", (AnalyzeMode.LIBRARY, None, "all"))]
```

来源模式测试也不得再期望隐式 `20`。

- [ ] **Step 2: 运行 MCP 定向测试并确认失败**

Run:

```powershell
python -m pytest tests/mcp/test_tools.py tests/mcp/test_server.py tests/mcp/test_contract.py -q
```

Expected: FAIL，当前 MCP schema 或 facade 仍暴露/传递 `limit`。

- [ ] **Step 3: 收口 MCP 签名**

将 MCP 工具改为：

```python
def skillcheck_analyze(
    mode: str,
    source: str | None = None,
    scope: str = "all",
    trigger_source: Literal["explicit_user", "agent_intent", "tool_chain"] = "agent_intent",
) -> dict[str, object]:
    return tools.analyze(mode, source, scope, trigger_source)
```

`SkillcheckMcpTools.analyze()` 同步删除 `limit` 参数、范围校验和 source 默认 20 的分支。保留 mode/source/trigger_source 校验。

- [ ] **Step 4: 更新 Agent 指令**

指令使用明确且不依赖参数的描述：

```text
skillcheck_analyze always analyzes the complete selected library or complete
validated incoming source. Do not attempt to bound the Skill count. Evidence
remains redacted and paginated.
```

- [ ] **Step 5: 运行 MCP 测试**

Run:

```powershell
python -m pytest tests/mcp -q
```

Expected: PASS，工具 schema 不再包含 `limit`。

- [ ] **Step 6: 提交 Task 2**

```powershell
git add src/skillcheck/mcp/server.py src/skillcheck/mcp/tools.py src/skillcheck/mcp/instructions.py tests/mcp
git commit -m "fix: make MCP governance analysis unbounded"
```

---

### Task 3: 持久化 Agent 选择是否已经初始化

**Files:**
- Modify: `src/skillcheck/config/models.py`
- Modify: `src/skillcheck/config/loader.py`
- Test: `tests/config/test_loader.py`
- Test: `tests/ui/test_agent_picker.py`

- [ ] **Step 1: 编写首次选择与再次选择的失败测试**

```python
def test_first_run_preselects_detected_agents() -> None:
    model = build_picker_model(
        [detected("codex"), detected("claude"), detected("cursor")],
        configured=[],
        selection_initialized=False,
    )
    assert checked(model) == ["codex", "claude", "cursor"]


def test_repeat_run_uses_exact_previous_selection() -> None:
    model = build_picker_model(
        [detected("codex"), detected("claude"), detected("cursor")],
        configured=["codex"],
        selection_initialized=True,
    )
    assert checked(model) == ["codex"]


def test_repeat_run_can_remember_an_intentional_empty_selection() -> None:
    model = build_picker_model(
        [detected("codex"), detected("claude")],
        configured=[],
        selection_initialized=True,
    )
    assert checked(model) == []
```

- [ ] **Step 2: 运行测试并确认旧模型失败**

Run:

```powershell
python -m pytest tests/config/test_loader.py tests/ui/test_agent_picker.py -q
```

Expected: FAIL，当前所有检测项都会因为 `detection is not None` 被勾选。

- [ ] **Step 3: 扩展配置模型**

```python
class TargetConfig(StrictConfig):
    configured: list[str] = Field(default_factory=list)
    selection_initialized: bool = False
    scope: Literal["global", "project"] = "global"
    last_validated: bool = False
```

旧配置缺少该字段时按 `False` 加载；一旦用户确认选择，包括确认空选择，都保存为 `True`。

- [ ] **Step 4: 修正 Picker 默认勾选规则**

```python
checked = available and (
    value in configured_values
    if selection_initialized
    else detection is not None
)
```

`AgentPicker.choose()` 接收并传递 `selection_initialized`。不可用 Agent 始终不能被返回。

- [ ] **Step 5: 运行配置与 UI 测试**

Run:

```powershell
python -m pytest tests/config/test_loader.py tests/ui/test_agent_picker.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交 Task 3**

```powershell
git add src/skillcheck/config/models.py src/skillcheck/config/loader.py src/skillcheck/ui/agent_picker.py tests/config/test_loader.py tests/ui/test_agent_picker.py
git commit -m "fix: remember exact Agent checkbox selection"
```

---

### Task 4: 建立可回滚的 Agent 接入差异预览

**Files:**
- Modify: `src/skillcheck/targets/base.py`
- Modify: `src/skillcheck/targets/_mcp.py`
- Modify: `src/skillcheck/targets/instructions.py`
- Modify: `src/skillcheck/pipelines/install_pipeline.py`
- Test: `tests/pipelines/test_install_pipeline.py`
- Test: `tests/targets/test_codex.py`
- Test: `tests/targets/test_claude.py`
- Test: `tests/targets/test_cursor.py`
- Test: `tests/targets/test_instructions.py`

- [ ] **Step 1: 编写新增、保留、移除差异测试**

```python
def test_reconcile_previews_added_kept_and_removed_agents(pipeline) -> None:
    preview = pipeline.preview_reconcile(
        previous=["codex", "claude"],
        selected=["codex", "cursor"],
        scope="global",
    )

    assert preview.added == ["cursor"]
    assert preview.kept == ["codex"]
    assert preview.removed == ["claude"]
```

再增加测试，验证 Claude 文件中的其他 MCP 条目和用户正文在移除后保持不变。

- [ ] **Step 2: 编写跨新增与移除的回滚失败测试**

```python
def test_reconcile_rolls_back_install_and_removal_when_validation_fails(pipeline) -> None:
    before = snapshot_managed_files(pipeline)
    preview = pipeline.preview_reconcile(["codex", "claude"], ["codex", "cursor"], "global")
    pipeline.fail_validation_for("cursor")

    with pytest.raises(RuntimeError):
        pipeline.apply_reconcile(preview, confirmed=True)

    assert snapshot_managed_files(pipeline) == before
```

- [ ] **Step 3: 运行 pipeline/target 测试并确认失败**

Run:

```powershell
python -m pytest tests/pipelines/test_install_pipeline.py tests/targets -q
```

Expected: FAIL，当前 pipeline 只能生成安装预览，移除方法会直接写文件，无法进入同一回滚事务。

- [ ] **Step 4: 为移除操作增加纯预览能力**

在 Target 协议和实现中增加：

```python
def preview_uninstall(self, scope: str) -> ConfigChange: ...
def preview_uninstall_instructions(self, scope: str) -> InstructionChange: ...
def validate_absent(self, scope: str) -> bool: ...
def validate_instructions_absent(self, scope: str) -> bool: ...
```

两个 preview 方法只返回移除 Skillcheck 受管内容后的 `after_text` 和当前哈希，不写文件。两个 absent 校验分别确认名为 `skillcheck` 的 MCP 条目和 Skillcheck 标记块已经不存在。现有 `uninstall()` 可以复用预览后再应用，以保持兼容。

- [ ] **Step 5: 定义 reconciliation 模型**

```python
class InstallReconcilePreview(BaseModel):
    previous: list[str]
    selected: list[str]
    added: list[str]
    kept: list[str]
    removed: list[str]
    scope: Literal["global", "project"]
    changes: list[FileChangePreview]
```

同时扩展文件预览，使回滚和输出能够指出归属：

```python
class FileChangePreview(BaseModel):
    agent: str
    operation: Literal["install", "remove"]
    path: Path
    before_hash: str | None
    after_text: str
    kind: Literal["mcp", "instructions"]
```

`preview_reconcile()` 对 selected 生成安装/修复预览，对 removed 生成移除预览；kept 也执行幂等预览，以修复手工破坏的受管条目。

- [ ] **Step 6: 原子应用并验证最终状态**

`apply_reconcile()` 复用 compare-and-swap 和 `_rollback()`，在持久化配置前验证：

```python
for agent in preview.selected:
    assert target.validate(scope)
    assert target.validate_instructions(scope)
for agent in preview.removed:
    assert target.validate_absent(scope)
    assert target.validate_instructions_absent(scope)
```

任何失败都恢复所有本次触及的文件。空 selected 时不启动 MCP smoke；只验证所有 removed 已解除。

- [ ] **Step 7: 运行 pipeline 与 adapter 测试**

Run:

```powershell
python -m pytest tests/pipelines/test_install_pipeline.py tests/targets -q
```

Expected: PASS，其他 MCP 和非标记用户正文保持不变。

- [ ] **Step 8: 提交 Task 4**

```powershell
git add src/skillcheck/targets src/skillcheck/pipelines/install_pipeline.py tests/pipelines/test_install_pipeline.py tests/targets
git commit -m "feat: reconcile exact Agent integrations atomically"
```

---

### Task 5: 修正 install 交互和非交互行为

**Files:**
- Modify: `src/skillcheck/commands/install.py`
- Modify: `src/skillcheck/ui/agent_picker.py`
- Test: `tests/commands/test_install_command.py`
- Test: `tests/ui/test_agent_picker.py`
- Test: `tests/release/test_install_entrypoints.py`

- [ ] **Step 1: 编写再次安装精确变更的命令测试**

```python
def test_repeat_install_uses_saved_checkboxes_and_persists_exact_selection(cli, configured_three_agents) -> None:
    configured_three_agents.config.targets.configured = ["codex", "claude"]
    configured_three_agents.config.targets.selection_initialized = True
    cli.picker_returns(["codex", "cursor"])

    result = cli.invoke(["install"])

    assert result.exit_code == 0
    assert cli.config.targets.configured == ["codex", "cursor"]
    assert cli.has_skillcheck_mcp("codex")
    assert not cli.has_skillcheck_mcp("claude")
    assert cli.has_skillcheck_mcp("cursor")
```

- [ ] **Step 2: 编写非交互不得自动全选测试**

```python
def test_non_interactive_install_without_target_changes_nothing(cli) -> None:
    cli.set_tty(False)

    result = cli.invoke(["install"])

    assert result.exit_code == 2
    assert "interactive terminal" in result.stdout
    assert cli.changed_files == []
```

再断言 `install --yes` 在没有显式 `--target` 时同样不自动全选。

- [ ] **Step 3: 编写空选择二次确认测试**

```python
def test_empty_selection_requires_explicit_disconnect_confirmation(cli) -> None:
    cli.picker_returns([])
    cli.confirm_returns(False)

    result = cli.invoke(["install"])

    assert result.exit_code == 0
    assert cli.config.targets.configured == ["codex", "claude"]
```

- [ ] **Step 4: 运行命令测试并确认失败**

Run:

```powershell
python -m pytest tests/commands/test_install_command.py tests/ui/test_agent_picker.py tests/release/test_install_entrypoints.py -q
```

Expected: FAIL，当前 `target="auto"`、非 TTY fallback 和追加式持久化会导致自动全选或无法取消旧选择。

- [ ] **Step 5: 将无参数与显式 target 分开**

把选项默认值改为 `None`：

```python
target: Annotated[str | None, typer.Option("--target")] = None
```

行为：

```python
if target is not None:
    selected = _selected_targets(pipeline, target)
elif not sys.stdin.isatty():
    raise ValueError(
        "interactive terminal required; use --target codex,claude --yes for automation"
    )
else:
    selected = AgentPicker().choose(
        detections,
        configured=loaded.targets.configured,
        selection_initialized=loaded.targets.selection_initialized,
    ).selected
```

`--yes` 只影响最终应用确认，不进入自动选择分支。

- [ ] **Step 6: 改为精确持久化并调用 reconciliation**

```python
def _persist_configured_targets(config_path, selected, location) -> None:
    loaded = load_config(config_path, create=False)
    loaded.targets.configured = list(dict.fromkeys(selected))
    loaded.targets.selection_initialized = True
    loaded.targets.scope = location
    loaded.targets.last_validated = True
    save_config(_config_path(config_path), loaded)
```

命令打印 added/kept/removed 预览，用户确认后调用 `apply_reconcile()`。空选择显示解除全部接入的专用确认文案。

- [ ] **Step 7: 运行 install 定向测试**

Run:

```powershell
python -m pytest tests/commands/test_install_command.py tests/ui/test_agent_picker.py tests/release/test_install_entrypoints.py -q
```

Expected: PASS。

- [ ] **Step 8: 提交 Task 5**

```powershell
git add src/skillcheck/commands/install.py src/skillcheck/ui/agent_picker.py tests/commands/test_install_command.py tests/ui/test_agent_picker.py tests/release/test_install_entrypoints.py
git commit -m "fix: apply exact interactive Agent selection"
```

---

### Task 6: 让 status、doctor 和 uninstall 遵守精确选择

**Files:**
- Modify: `src/skillcheck/commands/status.py`
- Modify: `src/skillcheck/commands/doctor.py`
- Modify: `src/skillcheck/lifecycle/doctor.py`
- Modify: `src/skillcheck/commands/uninstall.py`
- Test: `tests/commands/test_status.py`
- Test: `tests/commands/test_doctor.py`
- Test: `tests/commands/test_uninstall.py`
- Test: `tests/lifecycle/test_doctor.py`

- [ ] **Step 1: 编写后续服务范围失败测试**

```python
def test_doctor_checks_only_user_selected_integrations(configured_codex_only) -> None:
    report = run_doctor(configured_codex_only)
    assert checked_agent_names(report) == ["codex"]


def test_doctor_fix_does_not_auto_connect_detected_agents(intentional_empty_selection) -> None:
    run_doctor_fix(intentional_empty_selection)
    assert intentional_empty_selection.config.targets.configured == []
    assert intentional_empty_selection.changed_agent_files == []
```

- [ ] **Step 2: 运行定向测试并确认失败**

Run:

```powershell
python -m pytest tests/commands/test_status.py tests/commands/test_doctor.py tests/commands/test_uninstall.py tests/lifecycle/test_doctor.py -q
```

Expected: FAIL，当前 doctor 在配置列表为空时会回退到所有检测到的 Agent。

- [ ] **Step 3: 统一读取已确认选择**

当 `selection_initialized=True` 时，`status`、`doctor`、`doctor --fix` 和默认 `uninstall` 都只能使用 `targets.configured`。只有尚未初始化选择时，doctor 可以报告“尚未选择 Agent”，但不能自动写入检测结果。

索引根目录不随 Agent MCP 选择删除；`skillcheck init` 和全量治理仍扫描配置中的所有 Skill 根目录。

- [ ] **Step 4: 运行后续服务测试**

Run:

```powershell
python -m pytest tests/commands/test_status.py tests/commands/test_doctor.py tests/commands/test_uninstall.py tests/lifecycle/test_doctor.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 Task 6**

```powershell
git add src/skillcheck/commands/status.py src/skillcheck/commands/doctor.py src/skillcheck/lifecycle/doctor.py src/skillcheck/commands/uninstall.py tests/commands/test_status.py tests/commands/test_doctor.py tests/commands/test_uninstall.py tests/lifecycle/test_doctor.py
git commit -m "fix: scope lifecycle commands to selected Agents"
```

---

### Task 7: 增加真实用户旅程和性能回归门禁

**Files:**
- Create: `tests/acceptance/test_v051_full_scan_selection.py`
- Modify: `tests/acceptance/test_v5_user_journey.py`
- Modify: `tests/acceptance/trigger-policy-cases.json`

- [ ] **Step 1: 编写端到端用户旅程**

测试必须完成：

```python
def test_v051_full_scan_and_agent_reselection(v051_cli) -> None:
    v051_cli.install_selection(["codex", "claude"])
    assert v051_cli.status_agents() == ["codex", "claude"]

    v051_cli.install_selection(["codex", "cursor"])
    assert v051_cli.status_agents() == ["codex", "cursor"]
    assert v051_cli.skillcheck_entry_exists("codex")
    assert not v051_cli.skillcheck_entry_exists("claude")
    assert v051_cli.skillcheck_entry_exists("cursor")

    v051_cli.index_skills(168, duplicate_pair=(160, 167))
    analysis = v051_cli.mcp_analyze_library()
    assert analysis["summary"]["skills_considered"] == 168
    assert analysis_contains_pair(analysis, 160, 167)
```

- [ ] **Step 2: 添加全量分析性能记录**

为 168 个短 Skill 记录测试运行耗时，但使用宽松门禁避免不同 CI 主机抖动：

```python
started = time.monotonic()
result = analyzer.analyze_library()
assert time.monotonic() - started < 30
assert result.summary.skills_considered == 168
```

这个门禁只防止明显死循环或意外指数级实现，不用作微基准。

- [ ] **Step 3: 运行验收测试**

Run:

```powershell
python -m pytest tests/acceptance/test_v051_full_scan_selection.py tests/acceptance/test_v5_user_journey.py -q
```

Expected: PASS，测试使用隔离的 `SKILLCHECK_HOME`，不修改真实 Agent 配置和用户 Skill。

- [ ] **Step 4: 提交 Task 7**

```powershell
git add tests/acceptance
git commit -m "test: cover full scan and Agent reselection journey"
```

---

### Task 8: 更新 v0.5 文档和 v0.5.1 发布版本

**Files:**
- Modify: `README.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/agent-setup.md`
- Modify: `docs/release-checklist.md`
- Modify: `src/skillcheck/__init__.py`
- Modify: `pyproject.toml`
- Modify: `scripts/render_manifest.py`
- Modify: `tests/test_version.py`
- Modify: `tests/release/test_manifest.py`

- [ ] **Step 1: 更新用户文档**

README 和快速开始必须明确：

```text
- 首次安装默认勾选检测到的 Agent；再次安装回显上次选择。
- Space 增删选择，Enter 确认；本次选择是最终接入列表。
- 未选中的 Agent 不保留 Skillcheck MCP 条目或指令块。
- Agent 接入范围不等于 Skill 扫描范围；审计始终覆盖全部已索引 Skill。
- 证据分页只限制返回体积，不限制分析数量。
```

- [ ] **Step 2: 更新补丁版本**

```python
__version__ = "0.5.1"
```

同步更新 `pyproject.toml`、manifest 最低兼容版本和版本测试。Catalog schema 仍为 `5`。

- [ ] **Step 3: 运行版本与文档相关测试**

Run:

```powershell
python -m pytest tests/test_version.py tests/release/test_manifest.py tests/release/test_install_entrypoints.py -q
```

Expected: PASS。

- [ ] **Step 4: 提交 Task 8**

```powershell
git add README.md docs src/skillcheck/__init__.py pyproject.toml scripts/render_manifest.py tests/test_version.py tests/release/test_manifest.py
git commit -m "release: prepare skillcheck v0.5.1"
```

---

### Task 9: 执行全量质量门禁和发布

**Files:**
- Verify: `.github/workflows/release.yml`
- Verify: `install.ps1`
- Verify: `install.sh`

- [ ] **Step 1: 运行完整测试**

Run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

Expected: 全部通过，只允许已经记录的第三方 warning。

- [ ] **Step 2: 运行静态检查**

Run:

```powershell
python -m ruff check src tests scripts
```

Expected: `All checks passed!`

- [ ] **Step 3: 构建源码包和本机原生包**

Run:

```powershell
python -m build --no-isolation
python scripts/build_release.py --version 0.5.1 --platform windows --arch x64
dist/skillcheck-0.5.1-windows-x64/skillcheck.exe version
```

Expected: wheel、sdist 和 Windows x64 包构建成功，版本输出 `skillcheck 0.5.1`。

- [ ] **Step 4: 用隔离目录做原生包 smoke test**

使用新的临时 `SKILLCHECK_HOME`，验证：初始化 168 个 Skill、MCP 默认分析 168 个、选择两个 Agent 后只生成两个受管接入、`doctor --json` 无 error、`serve --mcp` 能启动。不得读取或修改真实用户 Agent 配置。

- [ ] **Step 5: 最终代码审查**

审查 `v0.5.0..HEAD`，阻塞条件包括：仍存在分析输入切片、非交互自动全选、配置列表追加合并、取消选择未移除受管接入、失败后部分写入、测试触及真实用户目录。

- [ ] **Step 6: 合并并发布**

```powershell
git push -u origin feat/skillcheck-v0.5.1
git switch main
git merge --ff-only feat/skillcheck-v0.5.1
git push origin main
git tag -a v0.5.1 -m "Release v0.5.1"
git push origin v0.5.1
```

Expected: GitHub Actions 构建 Windows x64、Linux x64、macOS x64、macOS arm64，并发布四个平台资产、manifest 和 `SHA256SUMS`。

- [ ] **Step 7: 核验远程 Release**

Run:

```powershell
gh run list --repo jjieYin/skillcheck --workflow Release --limit 3
gh release view v0.5.1 --repo jjieYin/skillcheck
```

Expected: Release workflow 为 `success`，`v0.5.1` 是 latest，四个平台安装包与校验文件齐全。

---

## 计划自检

- 全量本机库：Task 1、2、7 覆盖；
- 全量来源预检：Task 1、2 覆盖；
- 首次真正多选：Task 3、5 覆盖；
- 记住上次结果：Task 3、5、7 覆盖；
- 增加、保留、移除差异同步：Task 4、5、7 覆盖；
- 非交互不自动全选：Task 5 覆盖；
- status/doctor/uninstall 一致：Task 6 覆盖；
- Agent 接入范围与扫描范围分离：Task 6、8 覆盖；
- 失败原子回滚：Task 4 覆盖；
- v0.5.1 四平台发布：Task 8、9 覆盖；
- 计划中无未定义占位步骤，Catalog Schema 保持 v5，不修改真实用户 Skill。
