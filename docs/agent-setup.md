# Agent 接入

运行 `skillcheck setup`，向导会检测 Codex、Claude Code、Cursor，并默认选中已检测到的 Agent。

流程固定为：检测 → 选择全局/项目范围 → 预览配置 → 一次确认 → 写入并验证。

Adapter 只写入自己的 `skillcheck` MCP 条目，保留其他服务器和未知字段。重复执行 setup 不会产生重复条目；取消确认不会写入任何文件。

可用参数：

```text
skillcheck setup --agent codex --scope global --yes
skillcheck setup --agent claude --scope project
```

MCP 服务只提供 `skillcheck_summary`、`skillcheck_groups`、`skillcheck_report` 三个只读查询工具。

