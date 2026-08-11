# 复核与隐私

本地分析产生重复、冲突、质量和安全证据。Agent 只在你发起分析时使用自己的模型解释这些证据；无需为 Skillcheck 单独配置模型 API key。

Skillcheck 会对敏感正文显示做脱敏。MCP 不删除或改写用户 Skill；任何安装写入都必须经过 `skillcheck add` 的内容哈希复验和明确确认。
