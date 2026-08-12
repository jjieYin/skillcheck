# Agent 接入

Skillcheck 采用 CodeGraph 风格：CLI 只负责安装、初始化和维护；Agent 通过 MCP 获取证据，并用自身模型完成语义判断。

`skillcheck install` 只写入名为 `skillcheck` 的 MCP 条目及带标记的说明块。分析流程为 `skillcheck_analyze`、`skillcheck_evidence`、`skillcheck_save_review`；用户确认跨 Agent 镜像后才可调用 `skillcheck_save_sync_group`。其中 MCP 不写用户 Skill；保存的是治理结论。

安装向导维护一个持久化的 Agent 选择集合。首次运行以检测结果作为默认勾选；后续运行严格回显上次保存的集合，并将本次结果拆分为新增、保留、移除。移除操作只删除 Skillcheck 自己的 MCP 条目和指令标记，不会清理 Agent 的其他 MCP 或用户文本。`skillcheck status`、`doctor` 和 `uninstall` 也只针对这份已保存集合，不会因为检测到其他 Agent 就自动扩大范围。

`skillcheck_analyze` 对本机库默认执行完整索引分析。返回的证据仍按页读取并做脱敏，因此“分页”是返回控制，不是分析数量限制。

## 触发边界验收

Skillcheck 只应响应 Skills 治理请求：例如检查重复、重叠、冲突、安装前置检查、跨 Agent 镜像或同步组漂移。普通编码、调试、测试、文档润色，以及“使用一个已经选定的 Skill 完成任务”，都不应调用 Skillcheck。分析返回空候选时，也不应继续调用 `skillcheck_evidence` 或保存空审查。

可选的机器可读验收器接收 Agent 的非交互命令，并且只保存工具名、期望/实际结果和校验错误，不保存完整提示词或模型思考：

```text
python scripts/verify_trigger_policy.py \
  --agent codex \
  --command "codex exec --json {prompt}" \
  --cases tests/acceptance/trigger-policy-cases.json \
  --output build/trigger-policy/codex.json
```

Claude Code、Cursor 如果没有可稳定解析的非交互 JSON 输出，应采用下面的人工表格逐条记录，并附终端日志摘要或截图；不得把未执行的验收宣称为通过。

| 用例 | 期望 | 实际是否调用 `skillcheck_analyze` | 空候选后是否继续取证/保存 | 结果 |
| --- | --- | --- | --- | --- |
| 检查本机 Skills 是否重复 | 调用 |  |  |  |
| 安装前检查能力冲突 | 调用 |  |  |  |
| 检查跨 Agent 同步组漂移 | 调用 |  |  |  |
| 普通编码、测试或 README 润色 | 不调用 |  |  |  |
| 用户明确要求不使用 Skillcheck | 不调用 |  |  |  |
