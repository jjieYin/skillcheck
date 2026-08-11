# 故障排查

运行 `skillcheck doctor` 查看 v0.4 环境检查。`skillcheck doctor --fix` 只会重建空 catalog，或重写 Skillcheck 自己的 MCP/指令标记，绝不修改用户 Skills。

若 Agent 未显示工具，重新运行 `skillcheck install` 并重启 Agent。需要离线回退时运行 `skillcheck scan`。
