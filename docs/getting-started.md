# 快速开始

安装后运行 `skillcheck install`，在勾选向导中选择要接入的 Codex、Claude Code 或 Cursor；再运行 `skillcheck init` 建立个人 Skills 索引。首次安装默认勾选检测到的 Agent；再次运行时回显上一次的精确选择，取消勾选的 Agent 会被移除 Skillcheck 自己的 MCP 和指令标记。`--yes` 只跳过最终确认，不会自动全选；非交互终端必须显式传入 `--target`。

`skillcheck init` 会递归扫描每个配置根目录下任意深度的 `SKILL.md`。Agent 接入范围与 Skills 扫描范围相互独立：只接入一个 Agent，也仍会审计个人索引中的全部 Skills。

没有 Agent 时，`skillcheck scan` 仍会更新索引并生成本地确定性检查报告。

本地库分析默认覆盖完整索引，不存在隐藏的 20 条上限；只有证据分页限制单页返回量。

分析的 `scope` 可取 `all`、`global`、`project`、`custom`；`project` 使用当前项目路径，
来源分析始终保留暂存来源，只按 scope 过滤本地 catalog。`top_k` 只表示每个召回通道的
邻居数量，不是参与分析的 Skill 数量。索引同时保存 package `content_hash` 和
instruction `instruction_hash`，前者包含安全资源文件，后者只表示规范化指令。

普通编码、调试、测试、写作、仓库浏览或已经选定 Skill 的任务不会触发 Skillcheck。只有重复、重叠、冲突、安装前检查、跨 Agent 镜像、同步组和 Skills 治理请求才会进入 MCP 分析流程。
