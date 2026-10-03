# Skillcheck 治理审查算法 P0–P1 改进设计

## 1. 目标与成功标准

本次改造解决现有治理审查链路中的正确性和语义质量问题，不改变 Skillcheck 的产品安全边界。完成后应满足：

1. `AppConfig` 中的阈值、候选数、embedding 和安全配置真实控制 CLI、MCP 与来源预检的行为。
2. MCP 首次同步和增量同步都会为当前 embedding 签名生成向量；分析不会静默读取其他模型或其他维度的向量。
3. `scope` 有明确、可验证的过滤语义，且所有选中 Skill 都参与分析；`top_k` 只限制每个 Skill 的候选邻居。
4. Skill 自身的规范、安全和质量问题与 Skill 两两关系完全分离。
5. 冲突判断受语义阈值约束；分组不再因 A≈B、B≈C 而自动推导 A≈C。
6. 中文、英文和混合语言 Skill 均可通过离线词法通道参与候选召回；配置本地语义模型时可进一步提高语义召回。
7. 包内容完全相同与 SKILL.md 指令相同但资产不同可以被区分。
8. 库分析和来源预检使用同一套内建规范、安全规则；仅在用户明确配置后调用 SkillSpector。

## 2. 不变的产品边界

- MCP 仍只公开 `skillcheck_analyze`、`skillcheck_evidence`、`skillcheck_save_review` 和 `skillcheck_save_sync_group`。
- MCP 继续使用 stdio；证据继续分页、截断和脱敏。
- 当前连接的 Agent 负责语义终审；Skillcheck 不启动第二个 Agent。
- 未经用户确认，不写入审查结论或同步组；永不自动删除、重命名、覆盖或安装用户 Skill。
- `MIRRORED_COPY` 仍为 `monitor_only`，不会产生文件同步动作。
- 默认安装保持离线和轻量；Sentence Transformer、CrossEncoder、SkillSpector 均不得成为必装依赖。
- 本设计不包含 P2 的黄金数据集、线上阈值学习、自动模型训练或发布指标门禁。

## 3. 方案选择

采用“保守改造 + 混合候选召回 + 当前 Agent 终审”。

- 不采用纯规则方案：它无法解决中文改写和低词面重合的语义漏报。
- 不采用纯大模型方案：它会增加下载体积、冷启动、资源消耗和不确定性，也破坏默认离线体验。
- 不在本阶段引入第二个 reranker 模型：先把候选和证据结构做正确，继续由当前 Agent 完成高成本判断。

## 4. 目标架构

```text
配置 AppConfig
  → GovernancePolicy（唯一算法策略对象）
  → CatalogReconciler（快照 + 当前签名向量）
  → ScopeSelector（明确选择范围）
  → CompositeSkillValidator（规范 / 质量 / 安全 findings）
  → HybridCandidateRetriever
       ├─ package/instruction hash 候选
       ├─ Unicode 字符 n-gram / 单词 n-gram 候选
       └─ 已配置 embedding 候选
  → PairSignals（词法、向量、能力、权限、环境）
  → RuleDecisionEngine（只判断 Skill 间关系）
  → ConstrainedGrouper（成对冲突 + 完全连接相似组）
  → 结构化证据 + 当前 Agent 终审
```

## 5. P0 设计

### 5.1 单一策略入口

新增不可变的 `GovernancePolicy`，由 `AppConfig` 构造并传给 `GovernanceAnalyzer`。策略至少包含：

- `ThresholdConfig`；
- 当前 embedding 签名；
- `SecurityConfig`；
- 当前项目路径。

`LibraryAuditor` 必须使用 `thresholds.top_k`，`RuleDecisionEngine` 必须使用同一个 `ThresholdConfig`。测试可以显式传入策略；生产工厂不得依赖隐式默认值。

### 5.2 向量签名和生命周期

向量键不再只是用户填写的 `model_id`，而是稳定签名：

```text
<backend>:<model-or-id>:d<configured-dimensions>:r<algorithm-revision>
```

分析只读取当前签名。当前快照缺少此签名时，reconcile 必须补算；不同维度不得被静默跳过。MCP、初始化、手工同步和扫描管线必须通过同一个 embedding 工厂构造 reconciler。

旧向量不立即删除，便于回滚；它们不会被当前分析读取。

### 5.3 Scope 语义

保留字符串接口并只接受：

- `all`：所有启用根目录的当前 Skill；
- `global`：所有 `RootScope.GLOBAL` 根目录；
- `project`：`project_path` 等于当前运行项目的项目级根目录；
- `custom`：所有 `RootScope.CUSTOM` 根目录。

非法值立即报错。来源模式始终包含暂存来源，`scope` 只过滤与其比较的本机目录。所有选中 Skill 都参与哈希、校验和候选生成；`top_k` 不得截断输入集合。

### 5.4 Findings 与关系分离

`RuleDecisionEngine` 不再接收 findings，也不再因任意一侧存在高危 finding 返回 `UNSAFE`。输出拆为：

- `groups`：仅包含 Skill 间关系；
- `skill_findings`：包含 `skill_id` 与对应 `Finding`；
- `deterministic_findings`：保留一个版本的兼容平铺字段，但不再用于关系推断。

`SECURITY_ISSUE` 和 `QUALITY_ISSUE` 可继续作为读取历史 run 的枚举值，但新分析不再生成这两类候选组。

权限冲突只有在“同一资源存在 read/write 对立”且语义相似度达到 `conflict_similarity` 时成立。一个资源可同时保存多个权限模式，不能以后写值覆盖先写值。

### 5.5 分组语义

- `CONFLICT_CANDIDATE` 始终保持二元组。
- `HIGH_OVERLAP_CANDIDATE` 和 `VARIANT_CANDIDATE` 使用确定性的完全连接合并：两个组只有在所有跨组成员对都存在同关系边时才能合并。
- 缺少边不等同于相似，禁止单链传递。
- 每组保存全部成对证据及 `min_similarity`、`mean_similarity`、`max_similarity`；兼容字段 `similarity` 等于均值。
- `EXACT_DUPLICATE`、`MIRRORED_COPY` 的相似度统计固定为 `1.0`。

## 6. P1 设计

### 6.1 双重哈希与官方字段

保留 `content_hash` 作为完整 Skill 包哈希，新增 `instruction_hash`：只对规范化的 `SKILL.md` frontmatter 与正文计算，统一换行、去除行尾空白，并对 YAML 映射进行稳定排序。

- 同 `content_hash`：严格包重复或跨作用域镜像；
- 同 `instruction_hash` 但包哈希不同：进入高重合候选，并明确标注“指令相同、资产不同”，由 Agent 判断是否合并。

解析并持久化 Agent Skills 官方字段 `license`、`compatibility`、`metadata`、`allowed-tools`，同时保留项目扩展字段 `tools`、`permissions`、`environments`、`inputs`、`outputs`。升级 Catalog Schema 到 v6；v5 迁移时用 `content_hash` 保守回填 `instruction_hash`，随后 reconcile 重算真实值，避免把旧记录误判为相同指令。

### 6.2 混合候选召回

候选取三路并集：

1. `instruction_hash` 相同的候选，不受 `top_k` 限制；
2. 离线词法候选：CJK 使用 Unicode 字符 2–4 gram，拉丁文本使用规范化单词 unigram/bigram；
3. 当前 embedding 签名的向量候选。

每一路分别取 `top_k`，合并后按 Skill ID 去重。默认 hash embedding 使用相同的 Unicode-aware 特征规则。Sentence Transformer 仍通过现有可选依赖启用。

`PairSignals` 至少输出：

- `dense_similarity`；
- `lexical_similarity`；
- `semantic_similarity = max(可用的 dense, lexical)`；
- `capability_similarity`；
- `permission_conflict`；
- `environment_variant`；
- `instruction_hash_equal`、`package_hash_equal`。

结构化能力相似度只作为证据和关系门控，不在缺少标注数据时引入未经校准的复杂加权总分。

### 6.3 统一规范和安全校验

内建校验同时用于本机库与来源预检，并读取 Skill 目录中的所有安全文本文件。至少覆盖：

- 必填 `name`、`description`；
- `name` 格式及与目录名一致性；
- `description` 长度；
- `allowed-tools` 类型；
- 正文超过 500 行的质量提示；
- 现有 shell、凭据、隐藏字符、下载后执行、目录穿越/绝对路径规则。

缺失 `name` 时解析器仍可用目录名兼容索引，但必须保留并返回 `FMT001`，不能因 fallback 掩盖问题。

内建安全规则始终运行。`SecurityConfig.enabled` 仅控制外部 SkillSpector 集成；只有 `enabled=true` 且配置了 `skill_spector_command` 时才执行外部进程。未配置不产生逐 Skill 噪声；执行失败产生非阻断的能力 finding。

## 7. 持久化与兼容

- Catalog Schema 从 v5 原子迁移到 v6，失败必须回滚，原数据库保持可用。
- `analysis_runs.parameters_json` 记录算法版本、scope、阈值、embedding 签名和结构化 skill findings。
- 现有 `evidence` 表保存每个候选组的 pair signals 和分组统计，不新增第二套证据表。
- MCP 工具名称、写入确认和分页契约保持不变；返回模型只做加法式扩展。
- 历史 run 仍可读取；新字段缺失时按空列表或 `null` 处理。

## 8. 错误处理

- 配置非法：启动或分析前明确报错，不回退到隐藏默认值。
- 当前签名向量缺失：先由 reconcile 补算；仍缺失则返回带 skill ID 的 `AUDIT001`。
- 向量维度与记录不一致：返回 `AUDIT002`，不得静默跳过。
- 外部 SkillSpector 不可用或超时：返回能力 finding，内建校验结果仍有效。
- scope 非法或 project scope 无当前项目：明确报错，不扩大为 `all`。

## 9. 验收边界

P0 验收关注配置真实生效、向量一致、scope、关系/风险分离和无链式误组。P1 验收关注双哈希、官方字段、中文候选召回、统一校验与结构化证据。

P2 的大规模黄金集、Precision/Recall/F1/FPR、Recall@K、置信度校准和 shadow rollout 另立计划，不作为本次完成条件。
