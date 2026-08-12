# v0.5.1 发布清单

- 确认 `pyproject.toml` 与 `skillcheck.__version__` 都是 `0.5.1`。
- 确认默认本机分析覆盖完整索引；MCP 工具没有隐式 20 条限制。
- 确认首次 Agent 向导默认勾选检测项，后续运行回显上次选择，并按新增/保留/移除原子同步。
- 确认未勾选 Agent 的 Skillcheck MCP 条目和标记块会移除，但其他用户配置保持不变。
- 确认 Agent 接入范围与递归 Skills 扫描范围相互独立。
- 运行完整 pytest、Ruff、源码包构建和 Windows x64 原生 smoke test。
- 构建 Windows x64、Linux x64、macOS Intel、macOS Apple Silicon 资产、manifest 和 SHA256SUMS。
- 推送 `v0.5.1` 标签并检查 GitHub Release 的四个平台资产和校验文件。

- 确认 `pyproject.toml` 与 `skillcheck.__version__` 都是 `0.5.0`。
- 运行完整 pytest、Ruff、源码包构建和本机 Windows smoke test。
- 构建 Windows x64、Linux x64、macOS Intel、macOS Apple Silicon 资产、manifest 和 SHA256SUMS。
- 确认 v4 Catalog 会事务迁移到 v5；迁移失败时保留 v4 数据。
- 在已有 v4 Catalog、旧 Agent 配置和 doctor 非零状态的环境执行安装器；版本校验通过后安装必须继续，并给出后续诊断提示。
- 确认安装脚本只在交互终端启动 Agent 勾选向导，非交互安装不会自动修改 Agent 配置。
- 对 Codex、Claude Code、Cursor 执行触发边界验收；未实际验证的平台必须明确标记为未验证。
- 推送 `v0.5.0` 标签并检查 GitHub Release 的四个平台资产和校验文件。
