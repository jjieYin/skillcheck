# Skillcheck

让个人本地 Skills 保持清晰：自动发现重叠与风险，交给你正在使用的 Agent 做边界判断，但绝不自动修改你的 Skills。

## 安装

Windows：

```powershell
irm https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.ps1 | iex
```

macOS / Linux：

```sh
curl -fsSL https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.sh | sh
```

## 三步开始

```sh
skillcheck install
skillcheck init
```

随后直接在 Codex、Claude Code 或 Cursor 中说：

> 检查一下我本机的 Skills 有没有重复，并建议哪些该合并或改写边界。

Agent 会按需调用三个只读/受控工具：

```text
skillcheck_analyze → skillcheck_evidence → skillcheck_save_review
```

Agent 使用自己的模型理解 Skill 的真实边界；Skillcheck 负责本地目录、索引、确定性证据和保存你的治理决定。没有可用 Agent 时仍可运行：

```sh
skillcheck scan
```

安装新 Skill 时使用 `skillcheck add <目录|ZIP|GitHub URL>`。它会先暂存、检查、绑定内容哈希并展示结论；只有你确认后才写入目标 Agent 的 Skill 目录。

## 安全边界

- MCP 不会写入、删除、合并或重写用户 Skill。
- `add` 只接受明确确认后的受控写入，并拒绝确定性安全问题、路径逃逸和符号链接来源。
- 卸载默认只移除 Skillcheck 自己写入的 MCP 条目和指令标记，不触碰其他 MCP 配置或用户内容。

## 文档

- [快速开始](docs/getting-started.md)
- [Agent 接入](docs/agent-setup.md)
- [复核与隐私](docs/review-and-privacy.md)
- [故障排查](docs/troubleshooting.md)
- [发布清单](docs/release-checklist.md)
