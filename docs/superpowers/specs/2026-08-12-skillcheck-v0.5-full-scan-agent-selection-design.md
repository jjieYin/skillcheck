# Skillcheck v0.5 全量分析与 Agent 选择修订设计

## 1. 修订目标

本修订属于 Skillcheck v0.5 产品线，发布包使用补丁版本 `v0.5.1`，不引入 v0.6 的新架构。需要修复两个已经在真实使用中暴露的问题：

1. 所有审计入口默认分析完整输入集合，不再用 `20` 或其他数量截断本机库、目录、ZIP 或 GitHub 来源中的 Skill。
2. `skillcheck install` 使用真正的 Agent 多选向导，记住上一次确认结果，并将本次勾选结果作为最终接入状态进行差异同步。

## 2. 全量分析契约

`skillcheck_analyze` 不再公开 `limit` 参数。无论 `mode=library` 还是 `mode=source`，所有成功解析并通过来源安全检查的 Skill 都必须参与查重、作用域分类、质量检查和语义候选计算。

“全量分析”指参与分析的 Skill 数量等于当前作用域内的有效 Skill 数量，不代表把全部正文一次性返回给 Agent。以下边界继续保留：

- ZIP 解压大小、单文件大小、符号链接和目录穿越等来源安全限制；
- MCP 证据正文的脱敏、页大小和单次返回长度；
- 报告展示分页。

这些边界保护输入安全和输出体积，不得减少实际参与治理分析的 Skill 数量。

语义分析需要把“参与分析数量”和“每个 Skill 的候选邻居数”分开表达。本修订要求每个 Skill 都建立向量、执行规则和进入候选生成；实现可以使用分块计算降低内存，但不能通过截取前 N 个 Skill 获得性能。

## 3. Agent 多选状态

系统需要区分“检测到的 Agent”和“用户确认接入的 Agent”：

- 检测结果只决定哪些选项可用；
- 用户选择决定哪些 Agent 写入 Skillcheck MCP 条目和 Skillcheck 指令块；
- Skill 索引范围仍独立覆盖所有已配置扫描根目录，不因某个 Agent 未接入 MCP 而漏扫其 Skill。

首次进入向导时，默认勾选当前检测到且可配置的 Agent。首次确认后保存 `selection_initialized=true` 和精确的 `configured` 列表。再次进入向导时，严格按上一次保存结果回显：上次选中的保持勾选，新检测到的 Agent 只显示为可选，不自动新增。

用户确认后计算：

```text
新增 = 本次选择 - 上次选择
保留 = 本次选择 ∩ 上次选择
移除 = 上次选择 - 本次选择
```

执行结果必须满足：

- 新增 Agent：写入名为 `skillcheck` 的 MCP 条目和带 Skillcheck 标记的指令块；
- 保留 Agent：保持幂等，内容正确时不重复写入；
- 移除 Agent：仅删除 Skillcheck MCP 条目和 Skillcheck 标记块，保留该 Agent 的其他 MCP、设置和用户说明；
- 配置文件最终保存本次精确选择，不再把新选择追加到旧列表；
- 用户取消向导或拒绝确认时，任何 Agent 文件和 Skillcheck 配置都不改变。

若用户清空全部勾选，CLI 必须显示“将解除全部 Agent 接入”的二次确认。确认后删除所有受管接入并保存空列表；取消则保持原状。

## 4. 命令行行为

`skillcheck install` 无参数且处于交互终端时打开复选框：方向键移动、空格勾选或取消、Enter 确认、Esc 取消。

非交互环境不得因为无法展示向导而自动选择全部 Agent。无参数运行时返回清晰提示，要求用户在交互终端运行，或显式使用：

```text
skillcheck install --target codex,claude --yes
```

`--target all` 继续作为用户明确选择全部 Agent 的方式；`--target auto` 只用于显式兼容调用，不再作为无参数默认行为。`--yes` 只跳过最终确认，不能替用户选择 Agent。

## 5. 一致性与故障处理

新增和移除必须组成同一个预览和事务式应用过程。写入任意文件、校验或配置持久化失败时，恢复本次操作前的所有 MCP 文件、指令文件和 Skillcheck 配置。

应用后需要验证：

- 所有本次选中的 Agent 都存在正确 MCP 条目和指令块；
- 所有本次取消的 Agent 都不再包含 Skillcheck 受管内容；
- `status`、`doctor`、`uninstall` 使用同一份精确选择列表；
- `doctor --fix` 不得在空选择或非交互环境下重新接入所有检测到的 Agent。

## 6. 验收标准

- 构造 168 个 Skill，默认 MCP 本机库分析返回 `skills_considered=168`；把重复项放在排序第 21 位以后仍能发现。
- 来源目录、ZIP 或 GitHub 暂存目录包含超过 20 个 Skill 时，全部参与预检。
- 首次运行显示多选框；再次运行准确回显上次选择。
- 从 `codex,claude` 改为 `codex,cursor` 后，只新增 Cursor、保留 Codex、移除 Claude，并保存 `codex,cursor`。
- 非交互无参数安装不会写入任何 Agent，也不会自动全选。
- 清空选择只有在二次确认后才解除全部接入。
- 全量测试、Ruff、源码包和四平台 Release 工作流通过。
