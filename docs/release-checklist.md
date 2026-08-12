# v0.5.0 发布清单

- 确认 `pyproject.toml` 与 `skillcheck.__version__` 都是 `0.5.0`。
- 运行完整 pytest、Ruff、源码包构建和本机 Windows smoke test。
- 构建 Windows x64、Linux x64、macOS Intel、macOS Apple Silicon 资产、manifest 和 SHA256SUMS。
- 确认 v4 Catalog 会事务迁移到 v5；迁移失败时保留 v4 数据。
- 确认安装脚本只在交互终端启动 Agent 勾选向导，非交互安装不会自动修改 Agent 配置。
- 对 Codex、Claude Code、Cursor 执行触发边界验收；未实际验证的平台必须明确标记为未验证。
- 推送 `v0.5.0` 标签并检查 GitHub Release 的四个平台资产和校验文件。
