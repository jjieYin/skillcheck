# 故障排查

先运行：

```powershell
skillcheck doctor
```

常见情况：

- `未在 PATH 中找到 skillcheck`：重新打开终端，或把安装目录加入用户 PATH。
- `未检测到 Agent`：确认 Codex/Claude/Cursor 已安装，再运行 `skillcheck setup`。
- `配置文件无法解析`：先备份配置，修复 JSON/TOML/YAML 语法；工具不会覆盖损坏文件。
- `配置在确认后发生变化`：其他程序修改了配置，请重新执行预览和确认。
- `来源哈希变化`：安装前源内容发生变化，重新运行 `add` 检查。
- `doctor` 返回 1：表示提醒，不代表基础扫描不可用；返回 2 才表示错误。

