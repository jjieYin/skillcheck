# 故障排查

运行 `skillcheck doctor` 查看当前环境检查。`skillcheck doctor --fix` 只会重建空 catalog，或重写 Skillcheck 自己的 MCP/指令标记，绝不修改用户 Skills。

从旧版本升级时，安装器只把 `version` 检查作为阻断条件；旧 catalog 或 Agent 配置的 doctor 错误会显示为警告，不会阻止新程序安装。安装完成后运行 `skillcheck doctor`；如果报告提示可迁移的 v0.4 catalog，再运行 `skillcheck init` 完成事务迁移。

若 Agent 未显示工具，重新运行 `skillcheck install` 并重启 Agent。需要离线回退时运行 `skillcheck scan`。
