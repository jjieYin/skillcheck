# Release 清单

- 确认 `pyproject.toml` 和 `skillcheck.__version__` 都是发布版本。
- 运行 Ruff、完整 pytest、构建及四平台 smoke 检查。
- 发布 Windows x64、Linux x64、macOS Intel、macOS Apple Silicon 资产、manifest 和 SHA256SUMS。
- 检查安装脚本下载的最新 Release 和版本输出。
