# skillcheck

`skillcheck` 是一个面向个人的本地 Skills 管理与检查工具：在安装新 Skill 前，或定期整理已有 Skill 时，自动发现重复、边界重叠、环境变体、权限冲突和安全问题，并给出“保留、合并、改名、重写边界或人工复核”的建议。

它只生成报告和建议，不会自动删除、合并或改写你的 Skill。

## 你可以用它做什么

- 扫描本机已有的 Codex、Claude Code、Cursor、Agents 等 Skill 目录；
- 检查一个待安装的目录、ZIP 或 GitHub Skill 是否与现有库重复；
- 输出 Markdown 和 JSON 报告，便于阅读、归档或二次处理；
- 在需要时调用 Codex/Claude 做语义复核；默认不调用 Agent，也不联网。

## 5 分钟上手

### 1. 安装

Windows x64 普通用户无需 Python：

```powershell
irm https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.ps1 | iex
```

安装后重新打开终端，确认命令可用：

```powershell
skillcheck version
```

### macOS / Linux

如果 Release 已提供对应平台的自包含包，macOS 和 Linux 用户可以使用同一个安装入口：

```sh
curl -fsSL https://raw.githubusercontent.com/jjieYin/skillcheck/main/install.sh | sh
```

安装程序会根据系统和 CPU 架构自动选择资产：

- Linux x64：`skillcheck-<版本>-linux-x64.tar.gz`；
- macOS Intel：`skillcheck-<版本>-macos-x64.tar.gz`；
- macOS Apple Silicon：`skillcheck-<版本>-macos-arm64.tar.gz`。

命令入口默认放在 `~/.local/bin/skillcheck`。如果终端提示该目录不在 `PATH`，按当前 Shell 添加一次：

```sh
export PATH="$HOME/.local/bin:$PATH"
```

想永久生效，可以将这行加入 `~/.zshrc`（macOS 默认 Shell）或 `~/.bashrc`（Linux 常用 Shell），然后重新打开终端。

当前 `v0.3.0-beta` Release 先提供 Windows x64 包；如果对应的 macOS/Linux 资产尚未发布，可使用源码安装：

```sh
git clone https://github.com/jjieYin/skillcheck.git
cd skillcheck
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install .
skillcheck version
```

### 2. 扫描已有 Skills

扫描工具自动发现常见目录，更新本地索引，并生成 Markdown/JSON 报告：

```powershell
skillcheck scan
```

只扫描指定目录时：

```powershell
skillcheck scan "D:\my-skills"
```

### 3. 安装前检查新 Skill

先检查，不安装：

```powershell
skillcheck add "D:\downloads\new-skill" --check-only
```

检查通过后，确认并安装到目标 Agent：

```powershell
skillcheck add "D:\downloads\new-skill" --target codex
```

命令会先显示检查结论和报告路径，只有你确认后才会写入目标目录。

## 常用命令

| 命令 | 用途 |
| --- | --- |
| `skillcheck` | 打开交互式向导 |
| `skillcheck scan [目录]` | 扫描已有 Skills，更新索引并生成报告 |
| `skillcheck add SOURCE --check-only` | 检查新 Skill，不安装 |
| `skillcheck add SOURCE --target codex` | 检查并在确认后安装 |
| `skillcheck setup` | 检测并配置 Codex、Claude、Cursor 的 SkillCheck MCP 接入 |
| `skillcheck report latest` | 查看最近一次报告 |
| `skillcheck doctor` | 检查运行环境、索引、报告目录和 Agent 配置 |
| `skillcheck upgrade` | 更新自包含版本 |
| `skillcheck uninstall` | 卸载程序；默认保留 Skills、索引、报告和用户配置 |

`SOURCE` 支持三种形式：

- 本地目录：`D:\downloads\new-skill`；
- ZIP 文件：`D:\downloads\new-skill.zip`；
- HTTPS GitHub URL：`https://github.com/example/skill`。

## 一次扫描会做什么

```text
发现目录 → 解析 SKILL.md → 更新索引 → 本地规则检查
                                  ↓
                         哈希/离线向量相似度分析
                                  ↓
                           生成 MD/JSON 报告
                                  ↓
                   （可选）Codex/Claude 语义复核
```

本地分析会优先给出确定性结果；相似 Skill 可能被归为：

| 类型 | 典型建议 |
| --- | --- |
| `EXACT_DUPLICATE` | 保留一个权威副本，其他副本删除或停用前人工确认 |
| `HIGH_OVERLAP` | 合并能力，或重写两者的边界和触发条件 |
| `VARIANT_GROUP` | 保留变体，但改名并写清技术栈、环境或权限差异 |
| `CONFLICT_GROUP` | 检查读写权限和执行边界，必须人工复核 |
| `QUALITY_ISSUE` | 修复格式、质量或安全问题 |

## Agent 语义复核与隐私

默认扫描不启动 Codex/Claude，不发送 Skill 正文，也不需要配置模型。需要更细的边界判断时，显式指定：

```powershell
skillcheck scan --review codex
skillcheck add .\new-skill --review claude --check-only
```

复核只输出治理建议，不能授权安装、删除或修改文件。凭据、Token 和敏感正文会脱敏；复核失败时，基础本地报告仍然保留。

如果使用 OpenAI、千问等兼容模型，API key 只从环境变量读取，不写入 YAML。完整说明见 [`docs/review-and-privacy.md`](docs/review-and-privacy.md)。

## 报告和本地数据

默认数据目录为 `~/.skillcheck/`：

> 这里指的是运行 `skillcheck` 的用户电脑上的目录，不是 GitHub 仓库目录。首次运行后工具会自动创建它。

```text
config.yaml   用户配置
index.db      本地 Skill 索引
reports/      Markdown/JSON 报告
staging/      ZIP/GitHub 临时内容
```

临时测试或多套环境可以设置：

```powershell
$env:SKILLCHECK_HOME = "D:\skillcheck-test"
```

## 其他安装方式

开发者可以在仓库根目录安装：

```powershell
python -m pip install -e ".[dev]"
skillcheck version
```

POSIX 系统的自包含安装入口是 `install.sh`；开发者也可以使用上面的源码安装方式。普通用户使用已发布的自包含包时不需要 Python。

## 文档

完整文档在 GitHub 仓库的 [`docs/`](https://github.com/jjieYin/skillcheck/tree/main/docs) 目录：

- [快速开始](https://github.com/jjieYin/skillcheck/blob/main/docs/getting-started.md)
- [Agent 接入](https://github.com/jjieYin/skillcheck/blob/main/docs/agent-setup.md)
- [复核与隐私](https://github.com/jjieYin/skillcheck/blob/main/docs/review-and-privacy.md)
- [故障排查](https://github.com/jjieYin/skillcheck/blob/main/docs/troubleshooting.md)
- [v1 到 v2 迁移](https://github.com/jjieYin/skillcheck/blob/main/docs/migration-v1-to-v2.md)
- [Release 验收清单](https://github.com/jjieYin/skillcheck/blob/main/docs/release-checklist.md)

## 兼容与边界

旧的 `init`、`audit`、`check`、`list`、`install` 命令仍保留一个兼容周期，但新项目建议统一使用 `setup`、`scan` 和 `add`。

当前版本是个人本地工具，不替代企业级 Registry、RBAC 或团队协作平台，也不提供自动删除、自动合并和自动修改 Skill。
