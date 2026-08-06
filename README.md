# skillcheck

`skillcheck` 是一个个人本地 Skill 盘点、重复审计和安装前检查工具。它先扫描
Codex、Claude Code、Cursor、Agents 等常见目录，再用确定性规则和本地向量检索
发现重复、边界重叠、环境变体、权限冲突和安全问题。审计只生成建议，不会自动
删除或改写现有 Skill。

## 安装

开发环境（Windows PowerShell 和 POSIX shell 均适用）：

```powershell
python -m pip install -e ".[dev]"
skillcheck version
```

```bash
python -m pip install -e '.[dev]'
skillcheck version
```

默认使用离线 hash embedding，不需要下载模型。需要本地语义模型时再安装：

```bash
python -m pip install -e '.[local-embedding]'
```

## 基本流程

```powershell
skillcheck init
skillcheck scan
skillcheck audit --no-llm
skillcheck check .\path\to\new-skill --no-llm
skillcheck report latest
```

`scan` 只盘点和更新索引；`audit` 不需要新的安装源，可以直接检查当前个人库；
`check` 支持本地目录、ZIP 和 HTTPS GitHub URL；只有报告允许且用户明确确认时，
`install` 才会重新获取并安装：

```powershell
skillcheck install SC-20260806-120000-deadbeef --target codex
```

常见选项：

```text
skillcheck scan --json
skillcheck list --duplicates --provider codex
skillcheck audit --path .\project\.agents\skills --refresh --no-llm
skillcheck check https://github.com/example/skill --top-k 5 --strict
skillcheck report show REPORT_ID --json
```

## 配置与隐私

配置默认写入 `~/.skillcheck/config.yaml`，索引写入 `index.db`，报告写入
`reports/`。可通过 `SKILLCHECK_HOME` 将全部状态放到临时目录，或通过
`--config` 指定配置文件。API key 只从环境变量读取，不会写入 YAML：

```yaml
llm:
  enabled: true
  provider: qwen
  model: qwen-plus
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key_env: DASHSCOPE_API_KEY
  allow_full_text: false
```

OpenAI 兼容服务只在 `enabled: true` 且对应环境变量存在时调用。默认不把完整
正文发送到远程模型；`allow_full_text: true` 才允许发送正文。检测到凭据或隐藏
Unicode 时，正文会被省略或脱敏。没有 LLM、网络或 SkillSpector 时，基础解析、
哈希重复、离线向量检索和内置安全规则仍可运行。

## 可选 SkillSpector

安装并把 `skillspector` 放入 PATH 后，可在配置中指定命令：

```yaml
security:
  enabled: true
  skill_spector_command: skillspector
  timeout_seconds: 30
```

工具不可用时报告会明确标记能力降级，不会把“未扫描”误报为“安全”。

## 如何阅读审计建议

审计组可能包含：

- `EXACT_DUPLICATE`：内容哈希一致，通常保留一个权威副本；
- `HIGH_OVERLAP`：任务与正文高度重叠，建议合并能力或补充边界；
- `VARIANT_GROUP`：环境、技术栈或权限不同，建议改名并写清触发条件；
- `CONFLICT_GROUP`：读写权限或执行边界相冲突，必须人工复核；
- `QUALITY_ISSUE`：格式、质量或安全检查发现问题。

Markdown 和 JSON 报告具有相同的报告 ID、决策、候选、证据和建议。安装会重新
获取原始源并校验报告中的内容哈希；源被修改、目标已存在或决策为合并/拒绝/不
安全时，安装会被阻断。

## 非目标

当前版本不提供自动删除、自动合并、自动修改 Skill，也不替代企业级 Registry、
RBAC 或远程团队协作平台。Agent Skill 包装和 MCP 服务应在 CLI 稳定后单独设计。
