# Skillcheck v0.5 产品需求与设计（草案）

- 状态：已完成方案讨论，等待书面评审
- 日期：2026-08-11
- 目标版本：v0.5.0
- 基线版本：v0.4.1
- 本期范围：首次使用体验、治理作用域、跨 Agent 镜像副本与同步组

## 1. 背景与问题

v0.4.1 已完成跨平台安装、本地 Skill 索引、确定性查重、MCP 证据查询和 Agent 语义复核，但仍有两个明显的产品问题。

第一，`skillcheck install` 使用参数或逗号分隔文本选择 Agent，不如 CodeGraph CLI 的交互式多选直观。个人用户首次安装时难以快速理解本机检测到了哪些 Agent、将修改哪些配置以及当前选择状态。

第二，当前全库分析可能把不同 Agent 下的相同 Skill 当作普通重复项。用户常常会按照使用习惯，把同一 Skill 同时配置给 Codex、Claude Code 和 Cursor。这是合理的跨 Agent 分发，不应默认产生删除建议。产品需要明确治理边界，并提供可选的同步组来监测这些副本的版本漂移。

## 2. 产品目标

1. 首次安装时通过跨平台多选界面接入一个或多个 Agent；
2. 以“Agent + 作用域 + 项目/目录”建立独立治理空间；
3. 区分同一空间内的真正重复和跨空间的镜像副本；
4. 自动发现镜像候选，由用户确认是否建立同步组；
5. 同步组默认只监测版本漂移，不自动复制、覆盖或删除 Skill；
6. Agent 负责解释语义和提出建议，CLI 继续控制所有 Skill 文件变更。

## 3. 非目标

- 不在 v0.5.0 增加新的 Agent 类型；
- 不增加常驻后台服务或桌面 GUI；
- 不自动把相似但内容不同的跨 Agent Skill 建成同步组；
- 不自动同步、覆盖、合并或删除任何 Skill 文件；
- 不改变现有 SHA-256、向量召回和 Agent 语义复核的基本分工。

## 4. 需求一：首次安装的 Agent 多选

### 4.1 目标交互

用户运行：

```text
skillcheck install
```

终端显示：

```text
? 选择要接入的 Agent（空格选择，回车确认）

❯ ◉ Codex CLI（已检测）
  ◯ Claude Code（已检测）
  ◯ Cursor（已检测）
```

操作约定：

- ↑ / ↓：移动光标；
- Space：选中或取消选中；
- Enter：确认选择；
- Esc：取消，不修改任何配置；
- 已检测且尚未配置的 Agent 默认选中；
- 已接入的 Agent 显示“已配置”并保持选中；
- 未检测到的 Agent 默认不选中，并明确显示状态。

### 4.2 写入与安全规则

- 确认前展示将写入的 MCP 配置和指令文件；
- `install` 只新增或更新选中的 Agent；
- 取消勾选不得删除已有配置；
- 移除单个 Agent 使用 `skillcheck uninstall --target <agent>`；
- `skillcheck uninstall --complete` 保留为完整卸载入口；
- 写入继续使用现有边界标记、幂等检查、MCP 启动检查和回滚机制。

### 4.3 安装脚本与非交互模式

- Windows、macOS 和 Linux 安装脚本在交互式终端中安装二进制后进入 Agent 多选；
- 非交互环境只安装二进制并提示后续运行 `skillcheck install`，不得静默修改 Agent 配置；
- 保留脚本和 CI 模式：

```text
skillcheck install --target codex,claude --yes
skillcheck install --target auto --yes
```

- 交互界面采用支持 Windows、macOS、Linux 的 Python TUI 组件；方向键不可用或输入被重定向时，回退到文本选择。

## 5. 需求二：治理作用域与重复语义

### 5.1 治理作用域

默认治理作用域由以下字段共同确定：

```text
Agent/provider + global/project/custom + project_path/root_id
```

典型治理空间包括：

```text
Codex 全局 Skill 库
Claude Code 全局 Skill 库
Cursor 全局规则库
某个项目的 .agents/skills
用户额外指定的自定义目录
```

同一治理空间内的完全相同内容属于真正重复；不同治理空间、不同 Agent 下的相同内容属于镜像副本。

### 5.2 关系分类

| 场景 | 关系 | 默认治理建议 |
|---|---|---|
| 同一治理空间内内容哈希相同 | `EXACT_DUPLICATE` | 进入删除、停用或合并候选 |
| 不同 Agent/治理空间内内容哈希相同 | `MIRRORED_COPY` | 不计入冗余，不提出删除建议 |
| 同步组内成员与权威源不一致 | `SYNC_GROUP_DRIFT` | 展示差异，建议人工处理 |
| 跨 Agent 内容仅相似但不相同 | 保持现有相似候选 | 默认不自动建立同步组 |

普通审计报告应单独统计镜像副本，不得把它们计入“真正冗余”。只有用户明确提出“跨 Agent 全局审计”或“检查分发情况”时，才展开镜像副本详情。

## 6. 需求三：跨 Agent 同步组

### 6.1 创建原则

同步组采用“自动发现候选 + 用户确认建立 + 默认只监测”的混合模式。

1. Skillcheck 根据“内容哈希相同、治理作用域不同”发现 `MIRRORED_COPY`；
2. 系统只生成候选，不自动建立同步关系；
3. 用户选择组内成员并指定一个权威源；
4. 创建时保存成员当前快照作为基线；
5. 策略固定为 `monitor_only`，不自动同步文件。

### 6.2 数据模型

同步组至少包含：

```text
group_id
name
authority_skill_id
member_skill_ids
policy = monitor_only
baseline_revision
created_at / updated_at
status
```

每个成员绑定：

```text
Agent/provider
治理作用域与 root_id
Skill ID
加入组时的 snapshot_id
加入组时与当前的 content_hash
角色：authority / mirror
```

一个 Skill 同一时间只能属于一个同步组，避免权威关系冲突。

### 6.3 状态与漂移判断

| 状态 | 判断条件 | 处理方式 |
|---|---|---|
| `IN_SYNC` | 所有成员当前哈希与权威源一致 | 无需操作 |
| `DRIFTED` | 权威源相对基线发生变化，镜像成员尚未更新 | 提示预览差异 |
| `DIVERGED` | 一个或多个镜像成员独立修改，或权威源和镜像均变化 | 要求人工决定保留哪一侧 |
| `BROKEN` | 权威源或必要成员被删除 | 不自动选择新权威源 |
| `INVALID_MEMBER` | 成员无法解析或处于 invalid 状态 | 提示修复或移出同步组 |

删除同步组只删除关系元数据，不删除任何 Skill 文件。

## 7. MCP、Agent 与 CLI 协作

### 7.1 MCP 返回

`skillcheck_analyze` 扩展返回：

- 同一治理空间内的真正重复；
- `MIRRORED_COPY` 候选；
- 已建立同步组的状态；
- `SYNC_GROUP_DRIFT`、成员缺失和成员无效问题。

`skillcheck_evidence` 扩展返回：

- 每个成员所属 Agent、目录和治理作用域；
- 当前快照、内容哈希和基线快照；
- 权威源与镜像成员的字段和正文差异；
- 证据是否 stale。

新增：

```text
skillcheck_save_sync_group
```

该工具只保存同步组元数据。保存前必须校验 `run_id`、候选组、成员、权威源、revision 和内容快照；证据过期时拒绝创建。

### 7.2 Agent 使用流程

```text
用户要求检查跨 Agent 分发
    ↓
skillcheck_analyze 返回 MIRRORED_COPY
    ↓
skillcheck_evidence 返回成员与差异
    ↓
Agent 解释权威源和同步组影响
    ↓
用户确认
    ↓
skillcheck_save_sync_group 保存关系
```

Agent 可以解释、建议和保存同步组关系，但不能复制、覆盖或删除 Skill 文件。

### 7.3 CLI 备用入口

```text
skillcheck groups
```

交互菜单：

```text
1. 查看镜像候选
2. 创建同步组
3. 查看版本漂移
4. 查看组内差异
5. 移除同步组
```

同时保留非交互子命令：

```text
skillcheck groups list
skillcheck groups show <group-id>
skillcheck groups create
skillcheck groups remove <group-id>
```

v0.5.0 只提供监测、取证和报告，不提供自动文件同步命令。

## 8. 报告呈现

普通报告摘要示例：

```text
真正冗余：2 组
跨 Agent 镜像副本：8 组（不计入冗余）
同步组：3 个
存在版本漂移：1 个
```

同步组详情示例：

```text
同步组：api-review
权威源：Codex/api-review（当前快照）
镜像成员：Claude/api-review（落后）
镜像成员：Cursor/api-review（落后）
状态：DRIFTED
建议：预览差异后决定是否同步
```

报告不得把 `MIRRORED_COPY` 表述为应删除的重复项，也不得把 `DRIFTED` 表述为自动覆盖指令。

## 9. 验收标准

### 9.1 首次安装

1. Windows、macOS、Linux 均可使用方向键、Space、Enter 和 Esc 完成多选；
2. 同时选择多个 Agent 时，各自 MCP 配置正确写入；
3. 取消操作后配置文件、索引和报告均不变化；
4. 已配置、已检测和未检测状态显示准确；
5. 非交互命令保持可用。

### 9.2 治理作用域与同步组

1. 同一 Agent、同一治理空间内的相同内容仍判定为 `EXACT_DUPLICATE`；
2. 不同 Agent 下的相同内容判定为 `MIRRORED_COPY`，不计入冗余；
3. 镜像候选未经用户确认不得自动建立同步组；
4. 建立同步组后，相同内容状态为 `IN_SYNC`；
5. 权威源更新后状态为 `DRIFTED`；
6. 镜像成员独立修改后状态为 `DIVERGED`；
7. 权威源删除后状态为 `BROKEN`，不得自动改选；
8. 创建同步组时证据 stale 必须拒绝保存；
9. 移除同步组不得删除或修改 Skill 文件；
10. CLI 与 MCP 的现有索引、报告、卸载和安全测试全部通过。

## 10. 后续版本候选

以下能力不进入 v0.5.0，在监测模型稳定后再评估：

- 预览并确认后，将权威源同步到镜像成员；
- 同步组历史趋势和版本时间线；
- Agent 专属适配层，允许同一逻辑 Skill 在不同 Agent 下保持受控差异；
- 从 Git 仓库或包管理器恢复缺失成员；
- 多设备之间的同步组。
