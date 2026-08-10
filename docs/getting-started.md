# 快速开始

`skillcheck` 面向个人本地 Skills 库，帮助发现重复、边界重叠、环境变体和安全问题。

## Windows 安装

```powershell
irm https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.ps1 | iex
```

安装后直接运行：

```powershell
skillcheck
skillcheck scan
skillcheck add .\path\to\new-skill --check-only
```

首次扫描会自动发现 Codex、Claude Code、Cursor 和 Agents 常见目录，并生成 Markdown/JSON 报告。

## 开发安装

```powershell
python -m pip install -e ".[dev]"
skillcheck version
```

