# Skillcheck v0.5 产品需求文档（草案）

- 状态：需求记录，暂不实施
- 日期：2026-08-11
- 目标版本：v0.5.x
- 关联版本：v0.4.1

## 1. 需求背景

当前 `skillcheck install` 使用命令行参数或逗号分隔文本选择 Agent。对于首次使用的个人用户，这种方式不如 CodeGraph CLI 直观，尤其是在同时检测到 Codex、Claude Code 和 Cursor 时，用户不容易理解当前选择状态。

## 2. 产品目标

将 Agent 选择改为终端交互式多选界面，使用户能够直观看到检测结果、当前选择和确认动作，同时保留脚本化安装能力。

## 3. 目标交互

运行：

```text
skillcheck install
```

显示：

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
- 已检测到的 Agent 默认选中；
- 未检测到的 Agent 可以展示，但默认不选中，并说明其状态。

## 4. 功能要求

### 4.1 Agent 检测

- 复用现有 Codex、Claude Code、Cursor 检测逻辑；
- 展示 Agent 名称、检测状态和配置范围；
- 对已接入的 Agent 标记“已配置”；
- 检测不到配置文件时不得把 Agent 误报为已接入。

### 4.2 多选与确认

- 支持一次选择多个 Agent；
- 确认前展示将要写入的 MCP 配置和指令文件；
- 用户取消时不写入配置；
- 配置写入仍保持现有的幂等、标记边界和校验逻辑。

### 4.3 安全边界

- `install` 默认只新增或更新用户选中的接入；
- 取消勾选不得直接删除已有 Agent 配置；
- 移除单个 Agent 使用后续的 `uninstall --target <agent>`；
- `uninstall --complete` 仍作为显式的完整卸载入口。

### 4.4 非交互兼容

保留脚本和 CI 使用方式：

```text
skillcheck install --target codex,claude --yes
skillcheck install --target auto --yes
```

当终端不支持交互式按键、输入被重定向或运行在 CI 环境时，自动回退到文本参数模式，并给出明确提示。

## 5. 验收标准

1. Windows、macOS 和 Linux 终端均可使用方向键、Space 和 Enter 完成多选；
2. 同时选择 Codex、Claude Code 和 Cursor 时，三个配置均能正确写入；
3. 按 Esc 或输入取消后，配置文件、索引和报告均不发生变化；
4. 已配置 Agent 的默认选中状态与实际配置一致；
5. 非交互命令的行为与当前版本兼容；
6. 现有 MCP 启动检查、配置标记校验和卸载保护测试全部通过。

## 6. 暂不纳入本需求

- 不改变 Skill 索引、查重和 Agent 复核算法；
- 不增加新的 Agent 类型；
- 不把交互式选择改造成常驻桌面 GUI；
- 不因取消勾选自动删除已有 MCP 或指令配置。

## 7. 后续设计决策

实现前需要进一步确定：

- 交互界面采用轻量第三方 TUI 库，还是使用标准库实现跨平台按键读取；
- 安装脚本是否直接进入多选界面，还是先安装 CLI、再由 `skillcheck install` 进入向导；
- 已接入 Agent 的“取消勾选”是否提供单独的移除提示；
- 检测不到的 Agent 是否允许用户手动展开并配置。
