# skillcheck

`skillcheck` 是一个个人本地 Skill 盘点、重复审计和安装前检查工具。

## 开发环境

```powershell
python -m pip install -e ".[dev]"
skillcheck version
```

后续命令会扫描 Codex、Claude Code、Cursor 等常见本地 Skill 目录，并支持
`scan`、`audit`、`check` 和确认式 `install`。
