# 复核与隐私

本地分析产生重复、冲突、质量和安全证据；pair evidence 会保存 dense/lexical/capability
信号以及最小、平均、最大相似度。格式、质量和安全 finding 始终绑定到具体 Skill，
不会因为一侧有风险就把整个 pair 标成安全问题。Agent 只在用户发起治理请求时用自身
模型解释这些证据。Skillcheck 不需要单独配置模型 API key。

敏感正文会脱敏，证据有大小上限。内建规范与安全扫描始终执行；SkillSpector 只有在
配置启用且提供命令时才运行，外部扫描失败不会阻断本地结果。MCP 不删除或改写用户
Skill；任何安装写入都必须经过内容哈希复验和明确确认。

分析运行只记录必要的治理元数据（例如触发来源 `explicit_user`、`agent_intent`、`tool_chain` 或 CLI），不保存完整用户提示词。合法 JSON 事件中的普通文本提及不会被当作工具调用；触发验收器只保留工具名、期望/实际结果、退出码和校验错误。

跨 Agent 内容相同的 Skill 会标记为 `MIRRORED_COPY`，不会自动建议删除。用户确认后可以建立 `monitor_only` 同步组；它只记录权威 Skill、镜像成员和基线快照，发现 `DRIFTED`、`DIVERGED` 或 `BROKEN` 时报告，不自动覆盖文件。
