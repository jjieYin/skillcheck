# Agent 接入

Skillcheck 采用 CodeGraph 风格：CLI 只负责安装、初始化和维护；Agent 通过 MCP 获取证据，并用自身模型完成语义判断。

`skillcheck install` 只写入名为 `skillcheck` 的 MCP 条目及带标记的说明块。分析流程为 `skillcheck_analyze`、`skillcheck_evidence`、`skillcheck_save_review`。其中 MCP 不写用户 Skill；保存的是治理结论。
