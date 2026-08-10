# v1 到 v2 迁移

旧命令在 v0.2/v1.0 保留一个兼容周期：

| 旧命令 | 推荐命令 |
| --- | --- |
| `init` | `setup` |
| `audit` | `scan` |
| `check SOURCE` | `add SOURCE --check-only` |
| `list` | `scan` 后查看报告 |
| `install REPORT_ID` | `add SOURCE --target AGENT` |

首次读取 v1 配置时会写入同目录的 `config.yaml.v1.bak`，并把旧顶层扫描路径迁移到 `scan.extra_paths`。

v2 默认关闭旧的直接 LLM API 兼容调用；需要复核时使用 Codex/Claude CLI 或显式配置兼容模式。索引、报告、Skills 和用户配置均不会自动删除。

