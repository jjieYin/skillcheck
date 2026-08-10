# Release Checklist

- [ ] 五个平台资产构建成功
- [ ] 所有资产 SHA-256 与 Manifest 一致
- [ ] Windows 干净用户环境无需 Python 完成安装
- [ ] setup 重复执行不产生重复配置
- [ ] scan 默认不调用 Agent
- [ ] Codex/Claude 失败仍保留基础报告
- [ ] add 安装前重新校验来源哈希
- [ ] upgrade 失败后旧版本仍可运行
- [ ] uninstall 默认保留 Skills、索引、报告和配置
- [ ] MCP 工具列表只包含三个只读工具
- [ ] 总覆盖率不低于 85%，安全写入模块不低于 95%

