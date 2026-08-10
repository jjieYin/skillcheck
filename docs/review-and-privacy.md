# 复核与隐私

扫描默认只使用本地确定性规则和离线 hash embedding，不启动 Codex/Claude，也不会联网。

需要语义复核时显式指定：

```powershell
skillcheck scan --review codex
skillcheck add .\new-skill --review claude --check-only
```

复核采用只读、临时会话和 JSON Schema 白名单。Agent 输出只能形成治理建议，不能授权安装、删除、修改文件。

凭据、Token、正文和敏感证据会脱敏；复核失败时基础扫描报告仍然保留。配置文件只从环境变量读取 API key，不写入 YAML。

