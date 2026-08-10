# Skillcheck v0.4.0 CodeGraph Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Skillcheck 重构为 CodeGraph 模式：CLI 负责 Agent 接入、初始化、维护和受控写入，当前 Agent 通过三个 MCP 工具完成日常 Skills 治理，索引随 MCP 生命周期自动同步。

**Architecture:** 先在现有实现旁边建立新的 catalog、sync 和 governance 边界，再切换 MCP 与 CLI 主入口，最后删除 Review Adapter、菜单、兼容命令和旧数据库逻辑。SQLite 保存个人统一索引与证据，`watchfiles` 负责随 MCP 启停的文件监听；当前 Agent 是唯一语义模型，Skillcheck 不再启动任何 Agent 子进程。

**Tech Stack:** Python 3.11+、Typer、Pydantic v2、SQLite/FTS5、NumPy、本地 embedding、watchfiles、FastMCP、Pytest、Ruff、mypy、PyInstaller。

**Design:** `docs/superpowers/specs/2026-08-10-skillcheck-v0.4-codegraph-mode-design.md`

---

## 实施约束

- 每个 Task 独立实施、测试、审查和提交；不要跨 Task 混合修改。
- 每个行为先写失败测试，再实现最小代码。
- 新架构完成切换前保留旧模块，以便基线测试继续运行；切换后按 Task 12 的清单直接删除。
- 不实现 v0.3.x 配置、数据库、报告或命令兼容。
- MCP 不得写入用户 Skill 目录。
- 所有 Skill 文件写操作只能从 CLI 进入，并要求明确确认。
- 计划中的类型名、字段名和 MCP 工具名是后续 Task 的统一合同，不得自行改名。

## 文件结构锁定

```text
src/skillcheck/
├── catalog/
│   ├── __init__.py              # catalog 对外导出
│   ├── database.py              # v0.4 单一 Schema 初始化和连接
│   ├── schema.sql               # 完整新基线，不使用迁移链
│   ├── ids.py                   # root/skill/snapshot 稳定 ID
│   ├── models.py                # LibraryRoot、SkillSnapshot、SyncSummary
│   ├── repository.py            # roots、skills、snapshots、events、vectors
│   ├── discovery.py             # 标准目录和项目目录发现
│   ├── reconcile.py             # 差异计算和增量同步
│   └── watcher.py               # MCP 生命周期文件监听
├── governance/
│   ├── __init__.py
│   ├── models.py                # Analyze、Evidence、Decision 合同
│   ├── repository.py            # runs、groups、evidence、reviews
│   ├── analyzer.py              # library/source 本地分析
│   ├── reviews.py               # 保存 Agent 判断和 stale 校验
│   └── reports.py               # 新 Markdown/JSON 报告
├── mcp/
│   ├── instructions.py          # Agent 调用顺序与安全指令
│   ├── runtime.py               # connect-time sync + watcher 生命周期
│   ├── server.py                # FastMCP 注册三个工具
│   └── tools.py                 # MCP facade
├── targets/
│   ├── instructions.py          # AGENTS.md/CLAUDE.md 标记块
│   ├── codex.py                 # Codex MCP 配置适配器
│   ├── claude.py                # Claude MCP 配置适配器
│   └── cursor.py                # Cursor MCP 配置适配器
├── pipelines/
│   ├── install_pipeline.py      # Agent MCP + 指令配置
│   ├── init_pipeline.py         # 目录确认 + 首次索引
│   ├── sync_pipeline.py         # CLI 手动同步
│   ├── scan_pipeline.py         # 纯本地回退报告
│   └── add_pipeline.py          # 来源复验 + 受控安装
└── commands/
    ├── install.py
    ├── init.py
    ├── status.py
    ├── sync.py
    ├── scan.py
    └── add.py
```

---

### Task 1: 建立 v0.4 Catalog 数据库基线与领域模型

**Files:**
- Create: `src/skillcheck/catalog/__init__.py`
- Create: `src/skillcheck/catalog/models.py`
- Create: `src/skillcheck/catalog/database.py`
- Create: `src/skillcheck/catalog/schema.sql`
- Create: `tests/catalog/__init__.py`
- Create: `tests/catalog/test_schema.py`
- Create: `tests/catalog/test_models.py`

- [ ] **Step 1: 写数据库基线失败测试**

```python
import pytest

from skillcheck.catalog.database import CatalogDatabase, IncompatibleCatalogError


EXPECTED_TABLES = {
    "schema_meta",
    "library_roots",
    "skills",
    "skill_snapshots",
    "sync_events",
    "vectors",
    "analysis_runs",
    "candidate_groups",
    "group_members",
    "evidence",
    "agent_reviews",
    "reports",
    "source_preflights",
    "install_plans",
    "skill_fts",
}


def test_initialize_creates_complete_v4_schema(tmp_path):
    database = CatalogDatabase(tmp_path / "index.db")
    database.initialize()

    assert database.schema_version() == 4
    assert EXPECTED_TABLES <= database.table_names()


def test_incompatible_existing_database_is_rejected(tmp_path):
    path = tmp_path / "index.db"
    path.write_bytes(b"not-a-v4-database")

    with pytest.raises(IncompatibleCatalogError, match="重新初始化"):
        CatalogDatabase(path).initialize()
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/catalog/test_schema.py -v`

Expected: FAIL，`skillcheck.catalog` 尚不存在。

- [ ] **Step 3: 定义 v0.4 领域模型**

`src/skillcheck/catalog/models.py` 必须包含以下完整公开合同：

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RootScope(StrEnum):
    GLOBAL = "global"
    PROJECT = "project"
    CUSTOM = "custom"


class SkillStatus(StrEnum):
    ACTIVE = "active"
    INVALID = "invalid"
    MISSING = "missing"


class LibraryRoot(BaseModel):
    model_config = ConfigDict(frozen=True)
    root_id: str
    path: Path
    provider: str
    scope: RootScope
    project_path: Path | None = None
    enabled: bool = True


class SkillSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    snapshot_id: str
    skill_id: str
    root_id: str
    relative_path: str
    name: str
    description: str = ""
    body: str = ""
    content_hash: str
    status: SkillStatus = SkillStatus.ACTIVE
    tools: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    indexed_at: datetime
    parse_error: str | None = None


class SyncSummary(BaseModel):
    revision: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    invalid: int = 0
    pending: int = 0
    warnings: list[str] = Field(default_factory=list)


class SyncEvent(BaseModel):
    event_id: str
    revision: str
    started_at: datetime
    completed_at: datetime
    added: int = 0
    updated: int = 0
    removed: int = 0
    invalid: int = 0
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: 创建完整 Schema 与初始化器**

`schema.sql` 必须一次创建设计文档中的全部表，使用 `schema_meta` 中的 `schema_version=4`，并创建：

```sql
CREATE VIRTUAL TABLE skill_fts USING fts5(
    snapshot_id UNINDEXED,
    name,
    description,
    body
);
```

`CatalogDatabase.initialize()` 的行为必须是：空文件创建完整 Schema；现有 v4 数据库复用；其他内容抛出 `IncompatibleCatalogError`，不得迁移或覆盖。

- [ ] **Step 5: 运行模型与数据库测试**

Run: `python -m pytest tests/catalog/test_schema.py tests/catalog/test_models.py -v`

Expected: PASS。

- [ ] **Step 6: 提交 Task 1**

```bash
git add src/skillcheck/catalog tests/catalog
git commit -m "feat: add v0.4 catalog schema and models"
```

---

### Task 2: 实现稳定 ID 与 Catalog Repository

**Files:**
- Create: `src/skillcheck/catalog/ids.py`
- Create: `src/skillcheck/catalog/repository.py`
- Create: `tests/catalog/test_ids.py`
- Create: `tests/catalog/test_repository.py`

- [ ] **Step 1: 写稳定 ID 失败测试**

```python
from pathlib import Path

from skillcheck.catalog.ids import root_id, skill_id, snapshot_id


def test_ids_are_stable_across_absolute_parent_changes():
    first = skill_id("codex", "global", "api-test")
    second = skill_id("codex", "global", Path("api-test").as_posix())
    assert first == second
    assert first.startswith("skill-")


def test_snapshot_changes_only_when_content_changes():
    identity = skill_id("codex", "global", "api-test")
    assert snapshot_id(identity, "sha256:a") == snapshot_id(identity, "sha256:a")
    assert snapshot_id(identity, "sha256:a") != snapshot_id(identity, "sha256:b")
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/catalog/test_ids.py -v`

Expected: FAIL，ID 函数尚不存在。

- [ ] **Step 3: 实现统一 ID 规则**

```python
import hashlib
import os
from pathlib import Path


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def root_id(provider: str, scope: str, path: Path | str) -> str:
    normalized = os.path.normcase(str(Path(path).expanduser().resolve()))
    return f"root-{_digest(f'{provider}|{scope}|{normalized}')}"


def skill_id(provider: str, scope: str, relative_path: Path | str) -> str:
    relative = Path(relative_path).as_posix().strip("/").casefold()
    return f"skill-{_digest(f'{provider}|{scope}|{relative}')}"


def snapshot_id(identity: str, content_hash: str) -> str:
    return f"snapshot-{_digest(f'{identity}|{content_hash}')}"
```

- [ ] **Step 4: 写 Repository 失败测试**

测试必须覆盖：root 幂等 upsert、snapshot 成为当前版本、旧 snapshot 保留、删除 Skill 标记为 `missing`、FTS 返回当前 snapshot、vector 与 snapshot 绑定。

```python
def test_upsert_snapshot_keeps_history_and_moves_current_pointer(repository, root, snapshots):
    repository.upsert_root(root)
    repository.upsert_snapshot(snapshots[0])
    repository.upsert_snapshot(snapshots[1])

    current = repository.get_current_skill(snapshots[1].skill_id)
    assert current.snapshot_id == snapshots[1].snapshot_id
    assert repository.list_snapshots(snapshots[1].skill_id) == snapshots
```

- [ ] **Step 5: 实现 Repository**

`CatalogRepository` 提供固定方法：`upsert_root`、`list_roots`、`upsert_snapshot`、`mark_missing`、`get_current_skill`、`list_current_skills`、`list_snapshots`、`save_vector`、`get_vectors` 和 `record_sync_event`。

`upsert_snapshot` 必须在一个事务中完成当前指针和 FTS 更新：

```python
def upsert_snapshot(self, snapshot: SkillSnapshot) -> None:
    payload = snapshot.model_dump(mode="json")
    with self.database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT OR IGNORE INTO skill_snapshots
            (snapshot_id, skill_id, root_id, relative_path, name, description, body,
             content_hash, status, metadata_json, indexed_at, parse_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.skill_id,
                snapshot.root_id,
                snapshot.relative_path,
                snapshot.name,
                snapshot.description,
                snapshot.body,
                snapshot.content_hash,
                snapshot.status.value,
                json.dumps(
                    {
                        "tools": payload["tools"],
                        "permissions": payload["permissions"],
                        "environments": payload["environments"],
                        "inputs": payload["inputs"],
                        "outputs": payload["outputs"],
                    },
                    ensure_ascii=False,
                ),
                snapshot.indexed_at.isoformat(),
                snapshot.parse_error,
            ),
        )
        connection.execute(
            """
            INSERT INTO skills(skill_id, root_id, relative_path, current_snapshot_id, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(skill_id) DO UPDATE SET
              current_snapshot_id=excluded.current_snapshot_id,
              status=excluded.status
            """,
            (
                snapshot.skill_id,
                snapshot.root_id,
                snapshot.relative_path,
                snapshot.snapshot_id,
                snapshot.status.value,
            ),
        )
        connection.execute("DELETE FROM skill_fts WHERE snapshot_id = ?", (snapshot.snapshot_id,))
        connection.execute(
            "INSERT INTO skill_fts(snapshot_id, name, description, body) VALUES (?, ?, ?, ?)",
            (snapshot.snapshot_id, snapshot.name, snapshot.description, snapshot.body),
        )
        connection.commit()
```

所有 JSON 字段必须 `ensure_ascii=False`；所有多表写入使用单个事务。

- [ ] **Step 6: 运行 Repository 测试**

Run: `python -m pytest tests/catalog/test_ids.py tests/catalog/test_repository.py -v`

Expected: PASS。

- [ ] **Step 7: 提交 Task 2**

```bash
git add src/skillcheck/catalog tests/catalog
git commit -m "feat: persist stable skill snapshots"
```

---

### Task 3: 实现目录发现与 `skillcheck init`

**Files:**
- Create: `src/skillcheck/catalog/discovery.py`
- Create: `src/skillcheck/pipelines/init_pipeline.py`
- Create: `src/skillcheck/commands/init.py`
- Modify: `src/skillcheck/config/models.py`
- Modify: `src/skillcheck/config/loader.py`
- Modify: `src/skillcheck/app/main.py`
- Create: `tests/catalog/test_discovery_v4.py`
- Create: `tests/pipelines/test_init_pipeline.py`
- Create: `tests/commands/test_init.py`

- [ ] **Step 1: 写标准目录发现失败测试**

```python
def test_discover_roots_preserves_provider_scope_and_project(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".codex" / "skills").mkdir(parents=True)
    (project / ".claude" / "skills").mkdir(parents=True)

    roots = discover_library_roots(home=home, project=project)

    assert root_tuple(roots, home / ".codex" / "skills") == ("codex", "global", None)
    assert root_tuple(roots, project / ".claude" / "skills") == (
        "claude",
        "project",
        project.resolve(),
    )
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/catalog/test_discovery_v4.py -v`

Expected: FAIL，`discover_library_roots` 尚不存在。

- [ ] **Step 3: 实现发现规则**

`discover_library_roots(home, project, custom_paths=())` 只返回存在的目录，并为以下目录建立 `LibraryRoot`：

```text
~/.codex/skills
~/.agents/skills
~/.claude/skills
~/.cursor/rules
<project>/.codex/skills
<project>/.agents/skills
<project>/.claude/skills
<project>/.cursor/rules
```

自定义路径使用 provider=`custom`、scope=`custom`；路径按 `normcase(resolve())` 去重。

- [ ] **Step 4: 增加新 Catalog 配置字段**

在保留旧字段到 Task 12 的前提下，先加入：

```python
class CatalogConfig(BaseModel):
    initialized: bool = False
    roots: list[Path] = Field(default_factory=list)
    debounce_ms: int = Field(default=2000, ge=100, le=60000)
    reconcile_before_query: bool = True


class AppConfig(BaseModel):
    # 原字段暂时保留
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
```

`yaml_payload()` 必须输出 `catalog`，新配置文件必须是 UTF-8 且包含 `schema_version: 4`。

- [ ] **Step 5: 写并实现 InitPipeline**

在 `init_pipeline.py` 中先固定返回模型，避免命令层依赖裸字典：

```python
class InitPreview(BaseModel):
    roots: list[LibraryRoot]
    database_path: Path


class InitResult(BaseModel):
    changed: bool
    sync: SyncSummary
```

`InitPipeline` 固定提供 `discover(extra_paths)`、`preview(roots)` 和 `apply(preview, confirmed)`。`discover` 调用 `discover_library_roots`；`preview` 返回排序后的 roots 和将创建的数据库路径；`apply` 在未确认时返回 `InitResult(changed=False)`，确认后初始化数据库、逐个 upsert root、执行首次 reconcile、保存配置并返回同步摘要。

- [ ] **Step 6: 注册 `skillcheck init`**

命令合同：

```python
@app.command("init")
def init(
    paths: list[Path] | None = typer.Argument(None),
    yes: bool = typer.Option(False, "--yes"),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    pipeline = build_init_pipeline(config)
    roots = pipeline.discover(paths or [])
    preview = pipeline.preview(roots)
    for root in preview.roots:
        typer.echo(f"- {root.provider} {root.scope.value}: {root.path}")
    confirmed = yes or typer.confirm("确认建立以上 Skills 索引？")
    result = pipeline.apply(preview, confirmed=confirmed)
    if result.changed:
        typer.echo(
            f"初始化完成：新增 {result.sync.added}，"
            f"更新 {result.sync.updated}，无效 {result.sync.invalid}"
        )
    else:
        typer.echo("已取消，未修改配置或索引。")
```

终端必须展示目录、provider、scope 和首次同步摘要；未确认返回 0 且不改变状态。

- [ ] **Step 7: 运行 Task 3 测试**

Run: `python -m pytest tests/catalog/test_discovery_v4.py tests/pipelines/test_init_pipeline.py tests/commands/test_init.py -v`

Expected: PASS。

- [ ] **Step 8: 提交 Task 3**

```bash
git add src/skillcheck/catalog src/skillcheck/config src/skillcheck/pipelines/init_pipeline.py src/skillcheck/commands/init.py src/skillcheck/app/main.py tests
git commit -m "feat: initialize personal skill catalog"
```

---

### Task 4: 实现增量 Reconcile 与手动 `sync`

**Files:**
- Create: `src/skillcheck/catalog/reconcile.py`
- Create: `src/skillcheck/pipelines/sync_pipeline.py`
- Create: `src/skillcheck/commands/sync.py`
- Modify: `src/skillcheck/app/main.py`
- Create: `tests/catalog/test_reconcile.py`
- Create: `tests/pipelines/test_sync_pipeline.py`
- Create: `tests/commands/test_sync.py`

- [ ] **Step 1: 写新增、修改、删除失败测试**

```python
def test_reconcile_updates_only_changed_skills(catalog, root, skill_factory):
    first = skill_factory(root.path / "a", body="first")
    catalog.reconcile([root])
    revision_one = catalog.repository.current_revision()

    first.write_text("second", encoding="utf-8")
    skill_factory(root.path / "b", body="new")
    summary = catalog.reconcile([root])

    assert summary.added == 1
    assert summary.updated == 1
    assert summary.removed == 0
    assert summary.revision != revision_one


def test_reconcile_marks_deleted_skill_missing(catalog, root, skill_factory):
    marker = skill_factory(root.path / "removed", body="x")
    catalog.reconcile([root])
    marker.unlink()
    marker.parent.rmdir()

    summary = catalog.reconcile([root])
    assert summary.removed == 1
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/catalog/test_reconcile.py -v`

Expected: FAIL，reconcile 尚不存在。

- [ ] **Step 3: 实现差异算法**

`CatalogReconciler.reconcile(roots, changed_paths=None)` 必须：

1. 枚举 `SKILL.md` 所在 Skill 根目录。
2. 先比较 `(size, mtime_ns)`，变化时再计算内容哈希。
3. 通过 `core.parser.parse_skill` 解析有效 Skill。
4. 解析失败时保存 `INVALID` snapshot 和 `parse_error`，继续处理其他文件。
5. 只为新 snapshot 计算 embedding。
6. 标记已删除的当前 Skill 为 `MISSING`。
7. 在单次事务完成后生成新的 catalog revision。

`changed_paths` 存在时，只检查受影响 Skill 和对应根目录的删除情况。

- [ ] **Step 4: 实现 SyncPipeline 和命令**

```python
class SyncPipeline:
    def run(self, *, paths: list[Path] | None = None) -> SyncSummary:
        if not self.config.catalog.initialized:
            raise CatalogNotInitialized("请先运行 skillcheck init")
        roots = self.repository.list_roots()
        return self.reconciler.reconcile(roots, changed_paths=paths)
```

`skillcheck sync` 输出 revision、added、updated、removed、invalid；`--json` 输出 `SyncSummary.model_dump_json()`。

- [ ] **Step 5: 运行 Task 4 测试**

Run: `python -m pytest tests/catalog/test_reconcile.py tests/pipelines/test_sync_pipeline.py tests/commands/test_sync.py -v`

Expected: PASS。

- [ ] **Step 6: 提交 Task 4**

```bash
git add src/skillcheck/catalog/reconcile.py src/skillcheck/pipelines/sync_pipeline.py src/skillcheck/commands/sync.py src/skillcheck/app/main.py tests
git commit -m "feat: reconcile skill catalog incrementally"
```

---

### Task 5: 实现 MCP 生命周期文件监听与 stale 状态

**Files:**
- Modify: `pyproject.toml`
- Create: `src/skillcheck/catalog/watcher.py`
- Create: `src/skillcheck/mcp/runtime.py`
- Create: `tests/catalog/test_watcher.py`
- Create: `tests/mcp/test_runtime.py`

- [ ] **Step 1: 写 watcher 生命周期失败测试**

```python
def test_runtime_reconciles_before_first_query_and_stops_watcher(runtime):
    runtime.start()
    assert runtime.reconciler.calls == ["all"]
    assert runtime.watcher.started is True

    runtime.stop()
    assert runtime.watcher.stopped is True


def test_pending_change_marks_related_evidence_stale(runtime, skill_path):
    runtime.pending.add(skill_path)
    assert runtime.is_stale([skill_path]) is True


def test_runtime_registers_new_project_roots_on_connection(runtime, project_skill_dir):
    runtime.project_path = project_skill_dir.parents[2]
    runtime.start()
    root = runtime.repository.find_root(project_skill_dir)
    assert root.scope == RootScope.PROJECT
    assert root.project_path == runtime.project_path.resolve()
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/catalog/test_watcher.py tests/mcp/test_runtime.py -v`

Expected: FAIL，watcher/runtime 尚不存在。

- [ ] **Step 3: 添加 watchfiles 依赖**

在 `pyproject.toml` 的正式依赖中添加：

```toml
"watchfiles>=1,<2",
```

- [ ] **Step 4: 实现可注入的 CatalogWatcher**

`CatalogWatcher` 构造参数固定为 `roots`、`on_changes`、`debounce_ms=2000` 和可注入的 `watch_factory=watch`；公开 `start()`、`stop()` 和只读 `running`。后台线程必须为 daemon；`start()` 幂等；`stop()` 设置 stop event 并在 5 秒内 join；批量事件转换为绝对路径集合后只调用一次 `on_changes`；watchfiles 启动失败时保存 warning，不使 MCP 退出。

- [ ] **Step 5: 实现 McpRuntime**

`McpRuntime` 公开 `start()`、`stop()`、`before_query()`、`is_stale(paths)` 和 `status()`。`start()` 先基于 MCP 进程当前工作目录调用 `discover_library_roots()`，将新发现的 project-scope 根目录登记到统一 Catalog，再执行 connect-time reconcile 并启动 watcher；因此用户进入一个新项目时不必重新运行 `init`。`before_query()` 原子取出 pending 路径并执行一次增量 reconcile；`is_stale` 比较待处理路径和证据成员路径。未完成 `skillcheck init` 时只返回结构化 `not_initialized`，不得隐式创建数据库。

`status()` 的返回合同固定为：

```python
class RuntimeStatus(BaseModel):
    state: Literal["ready", "not_initialized", "degraded"]
    initialized: bool
    watching: bool
    revision: str | None
    pending_count: int
    project_roots_added: int = 0
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 6: 运行 Task 5 测试**

Run: `python -m pytest tests/catalog/test_watcher.py tests/mcp/test_runtime.py -v`

Expected: PASS，测试进程结束后没有存活 watcher 线程。

- [ ] **Step 7: 提交 Task 5**

```bash
git add pyproject.toml src/skillcheck/catalog/watcher.py src/skillcheck/mcp/runtime.py tests
git commit -m "feat: keep catalog synced during MCP sessions"
```

---

### Task 6: 实现 Governance Analyze 与 Evidence

**Files:**
- Create: `src/skillcheck/governance/__init__.py`
- Create: `src/skillcheck/governance/models.py`
- Create: `src/skillcheck/governance/repository.py`
- Create: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/core/audit.py`
- Create: `tests/governance/test_analyzer.py`
- Create: `tests/governance/test_evidence.py`

- [ ] **Step 1: 写 Analyze 合同失败测试**

```python
def forbidden(*args, **kwargs):
    raise AssertionError("governance analysis must not start an Agent subprocess")


def test_library_analyze_returns_prioritized_group_ids(analyzer, duplicate_catalog):
    result = analyzer.analyze_library(scope="all", limit=20)

    assert result.mode == AnalyzeMode.LIBRARY
    assert result.run_id.startswith("run-")
    assert result.summary.exact_duplicates == 1
    assert result.groups[0].relation == Relation.EXACT_DUPLICATE
    assert result.next_tool == "skillcheck_evidence"


def test_analyze_never_calls_an_agent_process(analyzer, monkeypatch):
    monkeypatch.setattr(subprocess, "run", forbidden)
    analyzer.analyze_library(scope="all", limit=20)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/governance/test_analyzer.py -v`

Expected: FAIL，governance 模块尚不存在。

- [ ] **Step 3: 定义固定治理合同**

```python
class AnalyzeMode(StrEnum):
    LIBRARY = "library"
    SOURCE = "source"


class Relation(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    HIGH_OVERLAP_CANDIDATE = "HIGH_OVERLAP_CANDIDATE"
    CONFLICT_CANDIDATE = "CONFLICT_CANDIDATE"
    VARIANT_CANDIDATE = "VARIANT_CANDIDATE"
    QUALITY_ISSUE = "QUALITY_ISSUE"
    SECURITY_ISSUE = "SECURITY_ISSUE"


class CandidateGroupSummary(BaseModel):
    group_id: str
    relation: Relation
    member_skill_ids: list[str]
    similarity: float | None = None
    requires_agent_judgment: bool


class AnalyzeSummary(BaseModel):
    skills_considered: int = 0
    exact_duplicates: int = 0
    overlap_candidates: int = 0
    conflict_candidates: int = 0
    variant_candidates: int = 0
    quality_issues: int = 0
    security_issues: int = 0


class AnalyzeResult(BaseModel):
    run_id: str
    mode: AnalyzeMode
    revision: str
    stale: bool
    summary: AnalyzeSummary
    groups: list[CandidateGroupSummary]
    deterministic_findings: list[Finding]
    next_tool: str | None
```

`Finding` 继续复用 `skillcheck.models.audit.Finding`，不得定义第二套本地问题模型。`limit` 使用 `Field(default=20, ge=1, le=100)`；超出范围由 MCP 输入校验直接拒绝。

- [ ] **Step 4: 映射现有本地分析能力**

重构 `core/audit.py` 的关系输出：

```python
RELATION_MAP = {
    "SIMILAR": "HIGH_OVERLAP_CANDIDATE",
    "CONFLICT": "CONFLICT_CANDIDATE",
    "VARIANT": "VARIANT_CANDIDATE",
    "UNSAFE": "SECURITY_ISSUE",
}
```

删除其中所有 LLM 文案；保留哈希重复、向量 Top-K、工具/权限/环境/输入输出差异和确定性 finding。

- [ ] **Step 5: 实现 Evidence 分页与脱敏**

```python
class EvidencePage(BaseModel):
    run_id: str
    group_id: str
    revision: str
    stale: bool
    page: int
    page_count: int
    members: list[EvidenceSkill]
    shared_capabilities: list[str]
    different_capabilities: list[str]
```

`GovernanceAnalyzer.evidence()` 必须验证 run/group 关系，默认每页正文不超过 12,000 字符，过滤 token、api_key、secret、password 字段，并把涉及 pending path 的结果标记为 `stale=True`。

- [ ] **Step 6: 运行 Task 6 测试**

Run: `python -m pytest tests/governance/test_analyzer.py tests/governance/test_evidence.py tests/core/test_local_analysis.py -v`

Expected: PASS。

- [ ] **Step 7: 提交 Task 6**

```bash
git add src/skillcheck/governance src/skillcheck/core/audit.py tests/governance tests/core
git commit -m "feat: expose local governance evidence"
```

---

### Task 7: 保存 Agent 判断并生成新版报告

**Files:**
- Create: `src/skillcheck/governance/reviews.py`
- Create: `src/skillcheck/governance/reports.py`
- Create: `src/skillcheck/models/governance.py`
- Modify: `src/skillcheck/governance/repository.py`
- Create: `tests/governance/test_reviews.py`
- Create: `tests/governance/test_reports.py`

- [ ] **Step 1: 写 stale 和 Schema 失败测试**

```python
def test_save_review_rejects_changed_snapshot(review_service, analyzed_run, catalog):
    catalog.change_skill(analyzed_run.member_skill_ids[0])

    with pytest.raises(StaleAnalysisError, match="重新读取证据"):
        review_service.save(analyzed_run.run_id, valid_decisions())


def test_save_review_writes_both_report_formats(review_service, analyzed_run):
    saved = review_service.save(analyzed_run.run_id, valid_decisions())
    assert saved.markdown_path.exists()
    assert saved.json_path.exists()
    assert "MERGE" in saved.markdown_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/governance/test_reviews.py tests/governance/test_reports.py -v`

Expected: FAIL，ReviewService 尚不存在。

- [ ] **Step 3: 定义结构化判断模型**

```python
class GovernanceDecision(StrEnum):
    KEEP_BOTH = "KEEP_BOTH"
    MERGE = "MERGE"
    DEPRECATE = "DEPRECATE"
    DELETE_DUPLICATE = "DELETE_DUPLICATE"
    RENAME = "RENAME"
    REWRITE_BOUNDARY = "REWRITE_BOUNDARY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class GroupDecision(BaseModel):
    group_id: str
    decision: GovernanceDecision
    canonical_skill: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=4000)
    recommendations: list[str] = Field(default_factory=list, max_length=20)


class SavedReview(BaseModel):
    review_id: str
    run_id: str
    revision: str
    decisions: list[GroupDecision]
    markdown_path: Path
    json_path: Path
```

- [ ] **Step 4: 实现 ReviewService 的强校验**

保存前依次验证：run 存在且完成、所有 group 属于该 run、group snapshot 集合未变化、`canonical_skill` 属于当前 group、每个 group 最多一个 decision。任何验证失败时不得产生 `agent_reviews` 或报告记录。

- [ ] **Step 5: 实现报告分层**

Markdown 固定包含：

```markdown
# Skillcheck 治理报告
## 本地确定性问题
## 相似候选与证据
## Agent 语义判断
## 建议的人工操作
## 安全边界
```

JSON 保存 run、revision、snapshot IDs、本地 findings、groups、Agent decisions 和生成时间；不得保存 Agent 凭据或隐藏配置。

- [ ] **Step 6: 运行 Task 7 测试**

Run: `python -m pytest tests/governance/test_reviews.py tests/governance/test_reports.py -v`

Expected: PASS。

- [ ] **Step 7: 提交 Task 7**

```bash
git add src/skillcheck/governance src/skillcheck/models/governance.py tests/governance
git commit -m "feat: persist agent governance decisions"
```

---

### Task 8: 将 MCP 切换为三个 CodeGraph 模式工具

**Files:**
- Rewrite: `src/skillcheck/mcp/instructions.py`
- Rewrite: `src/skillcheck/mcp/tools.py`
- Rewrite: `src/skillcheck/mcp/server.py`
- Modify: `src/skillcheck/commands/serve.py`
- Rewrite: `tests/mcp/test_tools.py`
- Rewrite: `tests/mcp/test_server.py`
- Create: `tests/mcp/test_contract.py`

- [ ] **Step 1: 写 MCP 名称和合同失败测试**

```python
EXPECTED_TOOLS = {
    "skillcheck_analyze",
    "skillcheck_evidence",
    "skillcheck_save_review",
}


def test_server_exposes_exact_v4_tool_set():
    assert TOOL_NAMES == EXPECTED_TOOLS


def test_analyze_requires_source_only_in_source_mode(queries):
    with pytest.raises(ValueError, match="source"):
        queries.analyze(mode="source", source=None, scope="all", limit=20)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/mcp -v`

Expected: FAIL，当前 MCP 仍暴露 summary/groups/report。

- [ ] **Step 3: 实现 MCP facade**

`SkillcheckMcpTools` 公开三个同名 Python 方法：`analyze(mode, source, scope, limit)`、`evidence(run_id, group_id, page, include_body)` 和 `save_review(run_id, decisions)`。`analyze` 验证 mode/source 后调用 runtime 与 GovernanceAnalyzer；`evidence` 先同步再分页读取证据；`save_review` 使用 `TypeAdapter(list[GroupDecision])` 校验输入，再调用 ReviewService。每个方法用 `model_dump(mode="json")` 返回 JSON 可序列化字典。

- [ ] **Step 4: 注册三个 FastMCP 工具**

`TOOL_NAMES` 必须精确等于测试集合。`run_stdio()`：

```python
runtime = build_runtime(config_path)
runtime.start()
try:
    create_server(SkillcheckMcpTools(runtime)).run("stdio")
finally:
    runtime.stop()
```

无论 MCP 正常退出还是异常，watcher 和数据库资源都必须释放。

- [ ] **Step 5: 写 MCP initialize 指令**

指令必须告诉 Agent：何时调用 analyze、何时读取 evidence、形成判断后调用 save_review、stale 时重新读取、不得修改 Skill，并明确本地确定性证据与 Agent 判断的区别。

- [ ] **Step 6: 运行 MCP 合同测试**

Run: `python -m pytest tests/mcp -v`

Expected: PASS，工具列表只有三个。

- [ ] **Step 7: 提交 Task 8**

```bash
git add src/skillcheck/mcp src/skillcheck/commands/serve.py tests/mcp
git commit -m "feat: switch MCP to agent-native governance"
```

---

### Task 9: 实现 `skillcheck install` 与 Agent 指令标记块

**Files:**
- Create: `src/skillcheck/targets/instructions.py`
- Create: `src/skillcheck/pipelines/install_pipeline.py`
- Create: `src/skillcheck/commands/install.py`
- Modify: `src/skillcheck/targets/base.py`
- Modify: `src/skillcheck/targets/_mcp.py`
- Modify: `src/skillcheck/targets/codex.py`
- Modify: `src/skillcheck/targets/claude.py`
- Modify: `src/skillcheck/targets/cursor.py`
- Modify: `src/skillcheck/app/main.py`
- Create: `tests/targets/test_instructions.py`
- Create: `tests/pipelines/test_install_pipeline.py`
- Create: `tests/commands/test_install_command.py`

- [ ] **Step 1: 写标记块幂等与卸载失败测试**

```python
def test_instruction_block_is_idempotent(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("# Existing\n", encoding="utf-8")

    manager = InstructionManager(path)
    manager.install(SKILLCHECK_INSTRUCTIONS)
    manager.install(SKILLCHECK_INSTRUCTIONS)

    text = path.read_text(encoding="utf-8")
    assert text.count("<!-- SKILLCHECK_START -->") == 1
    assert "# Existing" in text


def test_uninstall_removes_only_skillcheck_block(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(
        "before\n<!-- SKILLCHECK_START -->\nold\n<!-- SKILLCHECK_END -->\nafter\n",
        encoding="utf-8",
    )
    InstructionManager(path).uninstall()
    assert path.read_text(encoding="utf-8") == "before\nafter\n"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/targets/test_instructions.py -v`

Expected: FAIL，InstructionManager 尚不存在。

- [ ] **Step 3: 实现指令管理器**

固定标记：

```python
START = "<!-- SKILLCHECK_START -->"
END = "<!-- SKILLCHECK_END -->"
```

`preview/install/uninstall/validate` 使用现有 `atomic_replace` 和 before hash；marker 不完整时拒绝覆盖并报告人工修复；重复安装替换块内容而不追加。

- [ ] **Step 4: 扩展 Agent 检测结果**

`DetectionResult` 新增：

```python
instruction_path: Path | None = None
instructions_configured: bool = False
```

默认路径：Codex `~/.codex/AGENTS.md`、Claude `~/.claude/CLAUDE.md`、Cursor `~/.cursor/rules/skillcheck.mdc`。project scope 使用当前项目对应文件。

- [ ] **Step 5: 实现 InstallPipeline**

固定安装返回模型：

```python
class InstallDiscovery(BaseModel):
    agents: list[DetectionResult]


class FileChangePreview(BaseModel):
    path: Path
    before_hash: str | None
    after_text: str
    kind: Literal["mcp", "instructions"]


class InstallPreview(BaseModel):
    agents: list[str]
    scope: Literal["global", "project"]
    changes: list[FileChangePreview]


class InstallResult(BaseModel):
    changed_files: list[Path]
    validations: list[str]
```

`InstallPipeline` 公开 `discover()`、`preview(agents, scope)` 和 `apply(preview, confirmed)`。一次 preview 包含 MCP 配置和指令文件两类变化；未确认返回 `InstallResult(changed_files=[], validations=[])`。apply 逐项调用原子写入，任一文件失败时按相反顺序从 preview 的 before text 恢复；全部写入后验证 MCP entry、marker 和 `skillcheck serve --mcp` 冒烟启动。

- [ ] **Step 6: 实现 `skillcheck install`**

支持：

```text
--target auto|all|codex,claude,cursor
--location global|project
--yes
--print-config TARGET
```

默认交互检测并多选 Agent，写入前逐个显示准确文件路径；`--print-config` 只输出配置，不写文件。

- [ ] **Step 7: 运行 Task 9 测试**

Run: `python -m pytest tests/targets tests/pipelines/test_install_pipeline.py tests/commands/test_install_command.py -v`

Expected: PASS。

- [ ] **Step 8: 提交 Task 9**

```bash
git add src/skillcheck/targets src/skillcheck/pipelines/install_pipeline.py src/skillcheck/commands/install.py src/skillcheck/app/main.py tests
git commit -m "feat: wire skillcheck into local agents"
```

---

### Task 10: 切换 CLI 主流程、状态与纯本地扫描

**Files:**
- Create: `src/skillcheck/commands/status.py`
- Rewrite: `src/skillcheck/commands/scan.py`
- Rewrite: `src/skillcheck/pipelines/scan_pipeline.py`
- Rewrite: `src/skillcheck/app/context.py`
- Modify: `src/skillcheck/app/main.py`
- Create: `tests/commands/test_status.py`
- Rewrite: `tests/commands/test_scan.py`
- Rewrite: `tests/app/test_main.py`
- Create: `tests/acceptance/test_v4_cli_journey.py`

- [ ] **Step 1: 写无参数入口失败测试**

```python
def test_no_args_starts_install_when_not_configured(runner, empty_home):
    result = runner.invoke(app, [], input="n\n")
    assert "配置 Skillcheck Agent 接入" in result.stdout


def test_no_args_shows_status_when_initialized(runner, initialized_home):
    result = runner.invoke(app, [])
    assert "已接入 Agent" in result.stdout
    assert "请在 Agent 中直接提出 Skills 检查需求" in result.stdout
```

- [ ] **Step 2: 写本地 scan 不启动 Agent 的失败测试**

```python
def forbidden(*args, **kwargs):
    raise AssertionError("scan must not start an Agent subprocess")


def test_scan_is_local_only(runner, initialized_home, monkeypatch):
    monkeypatch.setattr(subprocess, "run", forbidden)
    result = runner.invoke(app, ["scan", "--json"])
    assert result.exit_code == 0
    assert '"agent_reviews": []' in result.stdout
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `python -m pytest tests/app/test_main.py tests/commands/test_status.py tests/commands/test_scan.py -v`

Expected: FAIL，当前入口仍显示菜单且 scan 仍包含 ReviewMode。

- [ ] **Step 4: 实现 status**

状态模型必须包含：configured agents、initialized、root count、skill count、revision、last sync、watch mode、pending count、warnings。`--json` 输出结构化状态；未初始化不是异常退出。

- [ ] **Step 5: 重写 scan 为纯本地回退**

`ScanPipeline.run(paths)` 只调用 sync、analyze_library 和 base report writer；不包含 review 字段和外部进程。命令参数只保留目录、`--json`、`--config`。

- [ ] **Step 6: 重写无参数行为**

`app.main` 根据 `config.targets.configured` 和 `config.catalog.initialized` 选择 install 引导或 status；删除对 `app.menu.run_menu` 的导入。

- [ ] **Step 7: 运行 Task 10 测试**

Run: `python -m pytest tests/app/test_main.py tests/commands/test_status.py tests/commands/test_scan.py tests/acceptance/test_v4_cli_journey.py -v`

Expected: PASS。

- [ ] **Step 8: 提交 Task 10**

```bash
git add src/skillcheck/app src/skillcheck/commands/status.py src/skillcheck/commands/scan.py src/skillcheck/pipelines/scan_pipeline.py tests
git commit -m "feat: make CLI a bootstrap and fallback interface"
```

---

### Task 11: 接通来源预检与受控 `add`

**Files:**
- Modify: `src/skillcheck/governance/analyzer.py`
- Modify: `src/skillcheck/governance/repository.py`
- Rewrite: `src/skillcheck/pipelines/add_pipeline.py`
- Rewrite: `src/skillcheck/commands/add.py`
- Modify: `src/skillcheck/installation/planner.py`
- Create: `tests/governance/test_source_preflight.py`
- Rewrite: `tests/pipelines/test_add_pipeline.py`
- Rewrite: `tests/commands/test_add.py`
- Create: `tests/acceptance/test_v4_add_journey.py`

- [ ] **Step 1: 写 source analyze 失败测试**

```python
def test_source_analyze_binds_run_to_source_hash(analyzer, source_skill):
    result = analyzer.analyze_source(str(source_skill), scope="all", limit=20)
    stored = analyzer.repository.get_source_preflight(result.run_id)
    assert stored.source_hash.startswith("sha256:")
    assert stored.source == str(source_skill)


def test_source_analyze_cleans_staging_after_failure(analyzer, unsafe_zip):
    with pytest.raises(SourceSafetyError):
        analyzer.analyze_source(str(unsafe_zip), scope="all", limit=20)
    assert list(analyzer.staging_root.iterdir()) == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/governance/test_source_preflight.py -v`

Expected: FAIL，source mode 尚未接入 staging。

- [ ] **Step 3: 实现 source mode**

使用现有 `sources.stage_source` 和安全限制；解析 incoming Skill，计算 source hash，与 catalog 当前 snapshots 召回 Top-K，保存 `source_preflights`、run、groups、evidence，最后清理临时目录。

保存合同固定为：

```python
class SourcePreflight(BaseModel):
    run_id: str
    source: str
    source_hash: str
    created_at: datetime
    expires_at: datetime
    deterministic_blockers: list[Finding] = Field(default_factory=list)
```

- [ ] **Step 4: 写 add 哈希复验失败测试**

```python
def test_add_rejects_changed_source_after_agent_review(pipeline, reviewed_source):
    prepared = pipeline.prepare(reviewed_source.source)
    reviewed_source.change_contents()

    with pytest.raises(ValueError, match="来源已变化"):
        pipeline.execute(prepared, confirmed=True)


def test_add_without_confirmation_writes_nothing(pipeline, reviewed_source):
    result = pipeline.run(reviewed_source.source, confirmed=False)
    assert result.installed_paths == []
```

- [ ] **Step 5: 重写 AddPipeline**

固定接口：

```python
class PreparedAdd(BaseModel):
    source: str
    source_hash: str
    review_state: Literal["reviewed", "local_only", "stale"]
    targets: list[str]
    target_paths: list[Path]
    files: list[str]
    deterministic_blockers: list[Finding] = Field(default_factory=list)
    expires_at: datetime


class AddResult(BaseModel):
    installed_paths: list[Path] = Field(default_factory=list)
    source_hash: str
```

`AddPipeline.prepare(source, targets)` 重新 stage 并计算 hash，读取相同 hash 的最新 source preflight 和 Agent review，创建带目标路径、文件清单和过期时间的 `PreparedAdd`；没有复核时状态为 `local_only`。`execute(prepared, confirmed)` 在未确认时返回空 `installed_paths`，确认后再次 stage、比较 source hash、验证确定性安全 finding，再调用 InstallationExecutor。是否允许安装只由确定性安全 finding 决定，Agent 建议作为用户决策证据，不直接执行写操作。

- [ ] **Step 6: 重写 add CLI**

移除 `--review` 和 `--check-only`。输出来源哈希、确定性阻断项、Agent 建议状态、目标路径和文件数量；`--yes` 仅用于显式自动化，默认必须确认。

- [ ] **Step 7: 运行 Task 11 测试**

Run: `python -m pytest tests/governance/test_source_preflight.py tests/pipelines/test_add_pipeline.py tests/commands/test_add.py tests/acceptance/test_v4_add_journey.py -v`

Expected: PASS。

- [ ] **Step 8: 提交 Task 11**

```bash
git add src/skillcheck/governance src/skillcheck/pipelines/add_pipeline.py src/skillcheck/commands/add.py src/skillcheck/installation/planner.py tests
git commit -m "feat: connect agent preflight to controlled installs"
```

---

### Task 12: 删除旧 Review、菜单、迁移和兼容实现

**Files:**
- Delete: `src/skillcheck/reviewers/`
- Delete: `src/skillcheck/pipelines/review_pipeline.py`
- Delete: `src/skillcheck/commands/setup.py`
- Delete: `src/skillcheck/commands/compat.py`
- Delete: `src/skillcheck/app/menu.py`
- Delete: `src/skillcheck/config/migration.py`
- Delete: `src/skillcheck/storage/migrations.py`
- Delete: `src/skillcheck/storage/schema/002_v2.sql`
- Delete: `src/skillcheck/llm.py`
- Delete: `src/skillcheck/models/review.py`
- Delete: `tests/reviewers/`
- Delete: `tests/commands/test_setup.py`
- Delete: `tests/commands/test_compat.py`
- Delete: `tests/app/test_menu.py`
- Delete: `tests/config/test_migration.py`
- Delete: `tests/test_llm.py`
- Modify: `src/skillcheck/config/models.py`
- Rewrite: `src/skillcheck/config/loader.py`
- Modify: `src/skillcheck/models/__init__.py`
- Modify: `src/skillcheck/app/main.py`
- Modify: `src/skillcheck/app/context.py`
- Modify: `pyproject.toml`
- Create: `tests/architecture/test_no_legacy_review.py`
- Rewrite: `tests/config/test_loader.py`

- [ ] **Step 1: 写禁止旧架构失败测试**

```python
from pathlib import Path


FORBIDDEN = (
    "skillcheck.reviewers",
    "ReviewMode",
    "--review",
    "CodexReviewAdapter",
    "ClaudeReviewAdapter",
    "LLMConfig",
)


def test_source_tree_contains_no_legacy_review_architecture():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/skillcheck").rglob("*.py")
    )
    for token in FORBIDDEN:
        assert token not in source
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/architecture/test_no_legacy_review.py -v`

Expected: FAIL，并列出仍存在的旧 token。

- [ ] **Step 3: 删除旧文件和注册入口**

按 Files 清单删除文件；`app/main.py` 不再注册 setup/compat；`models/__init__.py` 不再导出 AgentReview；`app/context.py` 只组装 catalog、reconciler、governance、reports、targets 和 installer。

- [ ] **Step 4: 收紧 AppConfig**

最终 `AppConfig` 只保留：

```python
class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[4] = 4
    catalog: CatalogConfig
    targets: TargetConfig = Field(default_factory=TargetConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    thresholds: ThresholdConfig = Field(default_factory=ThresholdConfig)
```

删除 `ReviewConfig`、`LLMConfig`、legacy 字段和 migration 调用。配置版本不是 4 时直接抛出清晰错误，不备份、不转换。

- [ ] **Step 5: 删除不再使用的依赖**

从 `pyproject.toml` 删除：

```toml
"openai>=1.40,<3",
```

保留 `httpx`，因为 GitHub source 和 release client 仍使用它。

- [ ] **Step 6: 检查旧 token 和导入**

Run: `rg -n "ReviewMode|--review|CodexReviewAdapter|ClaudeReviewAdapter|skillcheck\.reviewers|LLMConfig|skillcheck setup" src tests README.md docs`

Expected: 只允许在本实施计划和历史设计文档中出现；`src/` 和活动测试中为零。

- [ ] **Step 7: 运行完整测试**

Run: `python -m pytest -q`

Expected: PASS。

- [ ] **Step 8: 提交 Task 12**

```bash
git add -A src tests pyproject.toml
git commit -m "refactor: remove legacy agent review architecture"
```

---

### Task 13: 更新 doctor、uninstall 与配置诊断

**Files:**
- Modify: `src/skillcheck/lifecycle/doctor.py`
- Modify: `src/skillcheck/commands/doctor.py`
- Modify: `src/skillcheck/lifecycle/uninstall.py`
- Modify: `src/skillcheck/commands/uninstall.py`
- Modify: `tests/lifecycle/test_doctor.py`
- Modify: `tests/commands/test_doctor.py`
- Modify: `tests/lifecycle/test_uninstall.py`
- Modify: `tests/commands/test_uninstall.py`

- [ ] **Step 1: 写新版 doctor 失败测试**

```python
EXPECTED_CODES = {
    "runtime.version",
    "path.shadowing",
    "config.v4",
    "catalog.initialized",
    "catalog.integrity",
    "catalog.sync",
    "targets.detect",
    "targets.mcp",
    "targets.instructions",
    "mcp.handshake",
    "watcher.available",
    "reports.permissions",
}


def test_doctor_reports_exact_v4_checks(doctor):
    assert {item.code for item in doctor.run().checks} == EXPECTED_CODES
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/lifecycle/test_doctor.py tests/commands/test_doctor.py -v`

Expected: FAIL，当前仍包含 reviewers.detect 和旧 scan 修复提示。

- [ ] **Step 3: 更新 doctor**

删除 reviewer 检查；数据库修复建议改为重新执行 `skillcheck init`；增加 MCP marker、watchfiles import、最后同步错误和 catalog 初始化检查。`doctor --fix` 只能在用户确认后重写 Skillcheck MCP/marker 或重建空 catalog，不能修改 Skill。

- [ ] **Step 4: 写并实现精确卸载测试**

覆盖：只移除 MCP+marker、`--keep-cli`、`--keep-data`、完整卸载；始终保留用户 Skills；保留其他 MCP entry 和 Agent 指令内容。

- [ ] **Step 5: 运行 Task 13 测试**

Run: `python -m pytest tests/lifecycle/test_doctor.py tests/commands/test_doctor.py tests/lifecycle/test_uninstall.py tests/commands/test_uninstall.py -v`

Expected: PASS。

- [ ] **Step 6: 提交 Task 13**

```bash
git add src/skillcheck/lifecycle src/skillcheck/commands/doctor.py src/skillcheck/commands/uninstall.py tests
git commit -m "feat: diagnose and uninstall v0.4 integrations"
```

---

### Task 14: 完成端到端验收、文档与 v0.4.0 发布准备

**Files:**
- Rewrite: `README.md`
- Rewrite: `docs/getting-started.md`
- Rewrite: `docs/agent-setup.md`
- Rewrite: `docs/review-and-privacy.md`
- Rewrite: `docs/troubleshooting.md`
- Rewrite: `docs/release-checklist.md`
- Delete: `docs/migration-v1-to-v2.md`
- Modify: `src/skillcheck/__init__.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `skillcheck.spec`
- Rewrite: `tests/acceptance/test_user_journeys.py`
- Modify: `tests/release/test_assets.py`
- Modify: `tests/release/test_release_workflow.py`

- [ ] **Step 1: 写最终用户旅程**

`tests/acceptance/test_user_journeys.py` 固定覆盖：

```python
from hashlib import sha256


def tree_hash(root: Path) -> str:
    digest = sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def merge_decision(evidence: dict) -> list[dict]:
    members = evidence["members"]
    return [{
        "group_id": evidence["group_id"],
        "decision": "MERGE",
        "canonical_skill": members[0]["skill_id"],
        "confidence": 0.9,
        "reason": "两项能力边界和执行步骤重叠，保留证据中的第一项作为主 Skill。",
        "recommendations": ["合并独有步骤后再由用户手工处理源文件"],
    }]


def run_complete_governance(mcp_client) -> dict:
    analyzed = mcp_client.call("skillcheck_analyze", {"mode": "library"})
    group = analyzed["groups"][0]
    evidence = mcp_client.call(
        "skillcheck_evidence",
        {"run_id": analyzed["run_id"], "group_id": group["group_id"]},
    )
    return mcp_client.call(
        "skillcheck_save_review",
        {"run_id": analyzed["run_id"], "decisions": merge_decision(evidence)},
    )


def test_clean_user_reaches_agent_ready_state(binary, fake_agents, skill_library):
    binary.run("install", "--target", "codex,claude,cursor", "--location", "global", "--yes")
    binary.run("init", str(skill_library), "--yes")
    status = binary.run("status", "--json").json()
    assert status["initialized"] is True
    assert status["configured_agents"] == ["codex", "claude", "cursor"]


def test_agent_native_governance_journey(mcp_client, duplicate_library):
    analyzed = mcp_client.call("skillcheck_analyze", {"mode": "library"})
    evidence = mcp_client.call(
        "skillcheck_evidence",
        {"run_id": analyzed["run_id"], "group_id": analyzed["groups"][0]["group_id"]},
    )
    saved = mcp_client.call(
        "skillcheck_save_review",
        {"run_id": analyzed["run_id"], "decisions": merge_decision(evidence)},
    )
    assert Path(saved["markdown_path"]).exists()


def test_mcp_never_writes_skill_files(mcp_client, skill_library):
    before = tree_hash(skill_library)
    run_complete_governance(mcp_client)
    assert tree_hash(skill_library) == before
```

- [ ] **Step 2: 运行验收测试并修复真实缺口**

Run: `python -m pytest tests/acceptance -v`

Expected: PASS。不得通过 skip 隐藏 Windows 中文路径、MCP 生命周期或无 Agent 回退失败。

- [ ] **Step 3: 重写 README 首屏**

README 顺序固定为：一句价值说明、一行安装、`skillcheck install`、`skillcheck init`、在 Agent 中提出自然语言需求、三个 MCP 工具的自动流程、CLI 回退、安全边界、文档链接。不得再出现菜单、setup、`--review` 或额外模型/API Key 配置。

- [ ] **Step 4: 更新 Release 构建**

`skillcheck.spec` 必须收集 watchfiles 的平台二进制；Release workflow 的四个平台构建后依次执行：

```text
skillcheck version
skillcheck doctor --json
skillcheck serve --mcp 冒烟握手
```

Windows x64、Linux x64、macOS Intel、macOS Apple Silicon 资产和平台 manifest 必须全部存在后才能发布。

- [ ] **Step 5: 更新版本并运行质量门禁**

将 `src/skillcheck/__init__.py` 和 `pyproject.toml` 同时更新为：

```text
0.4.0
```

Run: `python -m ruff check scripts src tests`

Run: `python -m mypy src/skillcheck`

Run: `python -m pytest --cov=skillcheck --cov-report=term-missing --cov-fail-under=85`

Run: `python -m build`

Expected: 全部 PASS；架构测试确认旧 Review 逻辑为零；wheel/sdist 成功构建。

- [ ] **Step 6: 本地自包含包冒烟测试**

Run: `python scripts/build_release.py --version 0.4.0 --platform windows --arch x64`

Run: `dist/skillcheck-0.4.0-windows-x64/skillcheck.exe version`

Expected: `skillcheck 0.4.0`，不得包含 `legacy` 版本文案。

- [ ] **Step 7: 提交 Task 14**

```bash
git add -A README.md docs src/skillcheck/__init__.py pyproject.toml .github skillcheck.spec tests
git commit -m "release: prepare skillcheck v0.4.0"
```

---

## Task 审查与执行顺序

每个 Task 完成后必须单独执行：

1. 查看该 Task 的 `git diff --check`。
2. 运行该 Task 指定的目标测试。
3. 运行 `python -m ruff check` 覆盖改动文件。
4. 对新增公共模型和服务运行 mypy。
5. 审查是否越过 MCP 写入边界。
6. 形成一个独立 commit 后再进入下一个 Task。

里程碑：

| 里程碑 | Tasks | 可独立验收的结果 |
|---|---|---|
| Catalog Foundation | 1–4 | `init/sync` 可建立并增量维护个人索引 |
| Agent Runtime | 5–8 | MCP 自动同步并完成 analyze/evidence/save_review |
| Product Flow | 9–11 | install/init/Agent 日常使用/add 写入闭环 |
| Clean Break | 12–13 | 旧逻辑归零，doctor/uninstall 对应新架构 |
| Release | 14 | 文档、验收、四平台构建和 v0.4.0 版本完成 |

## 最终完成标准

- `skillcheck install` 能配置 Codex、Claude Code、Cursor 的 MCP 和指令标记块。
- `skillcheck init` 建立带 provider、scope、project 元数据的个人统一索引。
- MCP 连接时补同步，运行期间监听变化，退出时释放 watcher。
- MCP 默认且仅暴露 `skillcheck_analyze`、`skillcheck_evidence`、`skillcheck_save_review`。
- 当前 Agent 能保存结构化治理结论并得到 Markdown/JSON 报告。
- MCP 执行前后用户 Skill 目录哈希完全一致。
- `skillcheck add` 在用户确认前不产生目标文件，并在来源变化时拒绝安装。
- 无 Agent 时 `scan` 能生成纯本地报告。
- 源码中不存在 Review Adapter、ReviewMode、`--review`、旧菜单、旧迁移或直接 OpenAI 调用。
- Ruff、mypy、完整 pytest、MCP 合同测试、验收测试和四平台 Release 构建全部通过。
