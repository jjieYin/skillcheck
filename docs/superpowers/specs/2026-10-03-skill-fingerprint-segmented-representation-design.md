# Skill 指纹与分段表示算法改进设计

## 1. 背景

当前治理链路使用三个主要信号：完整包 `content_hash`、包含全部 frontmatter 与正文的 `instruction_hash`，以及默认 256 维特征哈希向量。2026-10-02 的对照实验确认：

- 只增加非行为 metadata 会改变 `instruction_hash`；
- 增加展示附件与增加改变行为的脚本，都会得到“指令相同、包不同”的相同结果；
- 将 `ALWAYS find root cause` 改为 `NEVER find root cause` 后，256、1024、4096 维相似度均约为 `0.9997`；
- 两个无关 Skill 加入相同公共模板后，相似度由约 `0.11` 升至 `0.88`，超过当前重叠阈值；
- API 联调完整版与轻量版的综合分数为 `0.8310`，当前返回 `PASS`；
- 增加向量维度可以降低部分哈希碰撞噪声，但不能解决否定语义和公共模板污染。

实验报告：`docs/superpowers/experiments/2026-10-02-hash-vector-baseline.md`。

## 2. 目标与成功标准

本设计采用“分层指纹 + 分段表示 + 多通道证据”，解决哈希语义边界不清、长文本单向量失真和公共模板误判问题。

完成后必须满足：

1. 非行为 metadata 和纯排版变化不改变行为指纹。
2. assets 变化只影响完整包指纹；scripts 变化必须影响执行指纹。
3. 核心规则从肯定变为否定时，输出明确的约束极性差异。
4. 两个无关 Skill 共享公共模板时，不能因此进入高重叠组。
5. 完整版与轻量版等同族 Skill 能进入重叠或变体候选，而不是静默 `PASS`。
6. 所有关系保留分通道证据，不再由一个 `max()` 总分决定。
7. 默认安装继续离线、轻量，不强制安装外部 embedding 或 reranker。
8. Catalog 迁移、MCP 工具名称、写入确认、证据分页和脱敏边界保持安全兼容。
9. 新向量模型通过稳定接口和 registry 接入，无需修改治理分析器、目录同步或 MCP 业务代码。

## 3. 非目标

- 本阶段不训练自有 embedding 或 reranker 模型。
- 本阶段不让 Skillcheck 自动删除、合并、改写或安装 Skill。
- 本阶段不把一般语义相似度直接解释为冲突概率。
- 本阶段不使用 LLM 执行不可复现的哈希、分段或约束抽取。
- 本阶段不承诺一个跨语言模型成为默认依赖；模型选择必须经过后续标注集比较。
- 本阶段不实现具体远程 embedding 供应商，只保留受隐私策略约束的接口扩展点。
- 本阶段不重做规范、安全和质量 findings；它们继续与 Skill 两两关系分离。

## 4. 方案选择

采用方案 A：分层指纹与分段表示。

不采用“只替换多语言 embedding”：它不能修复 metadata 干扰、脚本遗漏和指纹语义错误。

不采用“增加特征哈希维度并调阈值”：实验已证明 4096 维仍无法识别局部否定，也无法抑制公共模板。

## 5. 目标架构

```text
Skill 包
  → FingerprintBuilder
       ├─ package_hash：全部安全文件
       ├─ behavior_hash：行为字段 + SKILL.md 正文
       └─ execution_hash：scripts 下的执行文件
  → SkillSectionExtractor
       ├─ activation_text
       ├─ procedure_chunks
       ├─ constraint_clauses
       └─ capability_tokens
  → MultiChannelCandidateRetriever
       ├─ 指纹候选
       ├─ 模板降权后的词法候选
       └─ 可选语义模型候选
  → PairSignalsV2
       ├─ activation / procedure / constraint
       ├─ lexical / dense / capability
       └─ package / behavior / execution flags
  → RuleDecisionEngine
  → 关系专属分数 + 成对证据 + 当前 Agent 终审
```

## 6. 分层指纹

### 6.1 `package_hash`

`package_hash` 延续当前 `content_hash` 的完整包身份语义：

- 遍历 Skill 根目录下全部安全普通文件；
- 忽略 `.git`、符号链接和逃逸出根目录的路径；
- 按相对 POSIX 路径排序；
- 同时哈希相对路径和原始文件字节。

为兼容现有 Catalog 和安装链路，数据库列 `content_hash` 暂不重命名；模型和文档将其解释为 `package_hash`，并提供同名只读属性。

### 6.2 `behavior_hash`

`behavior_hash` 只表示 Skill 的声明行为，输入包括：

- `description`；
- `compatibility`；
- `allowed-tools`；
- 项目扩展字段 `tools`、`permissions`、`environments`、`inputs`、`outputs`；
- `SKILL.md` 正文。

以下字段不参与：

- `name`、`id`；
- `license`；
- 任意 `metadata`，包括作者和版本；
- 包内 assets、references 和 scripts 文件内容。

规范化规则：

- YAML 映射键稳定排序；
- 集合语义字段去重、排序并去除首尾空白；
- 正文统一为 LF、去除行尾空白并保留一个结尾换行；
- 正文段落顺序、标题层级、否定词、标点、命令参数和代码块内容保留；
- 哈希标识包含算法版本，例如 `sha256-v2:<digest>`。

`behavior_hash` 是精确行为指纹，不承担同义改写识别；不同文字但同义的 Skill 由候选检索处理。

### 6.3 `execution_hash`

`execution_hash` 表示本地可执行实现：

- 只扫描 `scripts/**` 下的安全普通文件；
- 使用相对路径和原始文件字节；
- 忽略符号链接和目录逃逸；
- 没有 scripts 时使用带版本的固定空指纹，文件不可读时使用 `null`，两者必须区分；
- 第一版不自动追踪正文中任意 references/assets 链接，避免把说明材料误认为执行代码。

固定空指纹只用于表达“两侧都没有脚本时执行实现等价”，不得作为独立候选召回键，否则所有无脚本 Skill 都会形成候选组合。

### 6.4 指纹关系

| package | behavior | execution | 关系含义 |
|---|---|---|---|
| 相同 | 相同 | 相同 | `EXACT_DUPLICATE` |
| 不同 | 相同 | 相同 | `BEHAVIOR_DUPLICATE_CANDIDATE`，通常是资源或说明差异 |
| 不同 | 相同 | 不同 | `IMPLEMENTATION_VARIANT_CANDIDATE` |
| 不同 | 不同 | 相同 | 同一执行实现的不同触发或使用方式，进入人工复核 |
| 不同 | 不同 | 不同 | 进入多通道候选分析 |

## 7. 分段表示

### 7.1 `SkillSections`

新增确定性结构：

```python
@dataclass(frozen=True)
class SkillSections:
    activation_text: str
    procedure_chunks: tuple[str, ...]
    constraint_clauses: tuple[ConstraintClause, ...]
    capability_tokens: tuple[str, ...]
```

其中：

- `activation_text`：`description` 及显式使用时机；
- `procedure_chunks`：正文按 Markdown 标题、列表步骤、段落和代码块切分；
- `constraint_clauses`：包含强制、禁止、允许、条件和例外词的句段；
- `capability_tokens`：字段限定的工具、权限、环境、输入和输出。

普通 chunk 最大 800 个 Unicode 字符；超长段落按 800 字符切分并保留 100 字符重叠。代码块独立成块，不与自然语言拼接。

### 7.2 约束结构

```python
@dataclass(frozen=True)
class ConstraintClause:
    text: str
    polarity: Literal["required", "forbidden", "allowed", "conditional"]
    action_features: tuple[str, ...]
```

第一版使用确定性中英文词表识别极性：

- required：`必须`、`务必`、`应当`、`must`、`always`、`required`；
- forbidden：`禁止`、`不得`、`不可`、`never`、`must not`、`do not`；
- allowed：`允许`、`可以`、`may`、`allowed`；
- conditional：`如果`、`仅当`、`除非`、`if`、`only if`、`unless`。

词表命中仅产生结构化信号，不直接判定冲突。双方约束动作高度相近但极性不同，输出 `constraint_polarity_mismatch=true` 供后续关系判定与 Agent 审查。

## 8. 词法与向量表示

### 8.1 模板降权词法通道

继续支持 CJK 2–4 gram 和拉丁 unigram/bigram，但改用库内文档频率进行降权：

```text
idf(feature) = log((N + 1) / (df(feature) + 1)) + 1
```

- 单个 chunk 中同一特征的词频上限为 3；
- 在大量 Skill 中反复出现的公共标题、模板句和通用词组权重降低；
- 文档频率按分析范围即时计算，暂不写入 Catalog；
- activation、procedure 和 constraints 分别计算词法相似度。

### 8.2 特征哈希重新定位

现有 `HashEmbeddingBackend` 保留为离线词法向量和兼容后端，但不得继续称为 dense semantic：

- 后端声明 `kind="lexical_hash"`；
- 输出记录为 `hashed_lexical_similarity`；
- 提高维度可以降低碰撞，但不改变关系语义；
- embedding signature 增加 sectioning 和 feature revision，旧向量不被新分析读取。

### 8.3 可选语义模型

向量模型通过统一接口接入，业务代码不得依赖 Sentence Transformer 或某个具体模型：

```python
EmbeddingChannel = Literal["activation", "procedure", "constraint"]

@dataclass(frozen=True)
class VectorizerDescriptor:
    backend: str
    model_id: str
    revision: str
    dimensions: int
    kind: Literal["lexical_hash", "semantic"]
    locality: Literal["local", "remote"]
    normalized: bool

@dataclass(frozen=True)
class VectorizationInput:
    key: str
    channel: EmbeddingChannel
    text: str

class VectorizationBackend(Protocol):
    descriptor: VectorizerDescriptor

    def encode(self, inputs: Sequence[VectorizationInput]) -> np.ndarray: ...
```

接口要求：

- 返回矩阵行顺序与输入一致；
- 行数、维度、有限数值和归一化声明必须由公共验证器检查；
- 空文本不提交给模型，调用方记录为缺失通道；
- backend 异常统一转换为 `EmbeddingUnavailable`，不得包含原始 Skill 正文或密钥；
- 配置只能选择已注册 backend，不允许从配置字符串动态导入任意 Python 模块；
- factory 和 registry 负责实例化，分析器、reconciler、CLI 与 MCP 只依赖 `VectorizationBackend`。

内置适配器：

- `HashVectorizationBackend`：默认离线 `lexical_hash` 后端；
- `SentenceTransformerVectorizationBackend`：可选本地 `semantic` 后端；
- `FakeVectorizationBackend`：只用于单元测试，不能从生产配置启用。

`EmbeddingConfig` 继续保留 `backend`、`model_id`、`dimensions`、`algorithm_revision` 和 `local_model`，并新增可选 `device`、正整数 `batch_size` 和 `threshold_profile`。旧配置可以原样加载；未设置 threshold profile 的语义模型只能参与候选召回。

接口允许未来增加远程 embedding adapter，但本阶段不实现具体远程供应商。远程 backend 后续必须同时满足：用户显式开启、`PrivacyConfig` 允许远程向量化、密钥不落库不写日志、请求超时和正文脱敏策略已配置。默认配置保持 `locality="local"`。

配置本地 Sentence Transformer 时：

- activation、procedure chunks 分别编码；
- 不把整个 Skill 拼成一个长字符串；
- `dense_similarity` 只代表真实语义模型通道；
- 模型加载失败时回退到离线词法候选，并明确返回能力 finding；
- 模型选择和默认阈值在不少于 100 组人工标注 Skill 对上确定。

本设计不指定具体模型名称，避免在没有本项目标注结果时把通用排行榜当作结论。

### 8.4 模型签名与阈值隔离

完整签名至少包含：

```text
<backend>:<model-id>:<model-revision>:d<dimensions>:<kind>:section-<revision>:feature-<revision>
```

不同签名产生的向量和相似度不可混用。每个语义模型必须绑定独立的阈值配置和评估记录；没有经过标注集校准的模型只能参与候选召回，不能驱动自动高重叠关系。更换模型、维度、归一化策略、分段或特征版本都会生成新签名并触发重建。

## 9. 候选召回

候选集合为以下通道的并集：

1. `behavior_hash` 相同的所有组合，不受 `top_k` 限制；
2. 双方都存在 scripts、非空 `execution_hash` 相同且行为不同的组合，不受 `top_k` 限制；
3. activation 词法 Top-K；
4. procedure chunk 词法 Top-K；
5. constraints 动作词法 Top-K；
6. 配置语义模型时的 activation 与 procedure dense Top-K。

`top_k` 只限制每个检索通道的邻居数，不限制分析输入 Skill 数。来源预检和库分析继续使用同一套检索器。

## 10. `PairSignalsV2`

新增信号：

```python
@dataclass(frozen=True)
class PairSignalsV2:
    package_hash_equal: bool
    behavior_hash_equal: bool
    execution_present_left: bool
    execution_present_right: bool
    execution_hash_equal: bool | None
    execution_equivalent: bool
    activation_lexical_similarity: float | None
    procedure_coverage_left: float | None
    procedure_coverage_right: float | None
    constraint_action_similarity: float | None
    constraint_polarity_mismatch: bool
    hashed_lexical_similarity: float | None
    activation_dense_similarity: float | None
    procedure_dense_coverage_left: float | None
    procedure_dense_coverage_right: float | None
    capability_similarity: float | None
    permission_difference: bool
    environment_variant: bool
```

procedure coverage 定义为：一侧非模板 chunk 中，相似度达到该通道 chunk 门槛的数量占比。必须保留左右两个方向，不能只取平均值，否则无法区分重复与功能包含。

`execution_hash_equal` 只有双方都存在可执行内容并成功计算时才返回布尔值，否则为 `None`。`execution_equivalent` 在双方都没有脚本，或双方非空执行哈希相同时为 `True`；读取失败不得视为等价。

现有 `semantic_similarity` 暂时保留为兼容字段：只有实际语义模型启用时才等于 relation 使用的 dense 分数；离线特征哈希不得填入此字段。新代码不得使用 `max(lexical, dense, hash_equal)` 生成统一分数。

## 11. 关系判定

关系采用门控条件和关系专属分数：

- `EXACT_DUPLICATE`：`package_hash_equal=true`，关系分数固定为 1.0；
- `BEHAVIOR_DUPLICATE_CANDIDATE`：behavior 相同、execution equivalent、package 不同，关系分数固定为 1.0；
- `IMPLEMENTATION_VARIANT_CANDIDATE`：behavior 相同、execution 不等价；
- `HIGH_OVERLAP_CANDIDATE`：activation 达到门槛、双方 procedure coverage 均达到门槛，且不存在未解释的 constraint polarity mismatch；关系分数取 activation 与双向 coverage 的最小值；
- `CONTAINMENT_CANDIDATE`：activation 达到门槛，一侧 procedure coverage 明显高于另一侧；关系证据必须指出覆盖方向；
- `CONSTRAINT_MISMATCH_CANDIDATE`：constraint action 达到门槛且极性不同；它表示需要审查的约束差异，不直接等同于最终冲突；
- 其他已召回但证据不充分的组合返回 `MANUAL_REVIEW` 或 `PASS`，并保存分通道证据。

初始阈值不得直接沿用旧 `semantic_similarity` 阈值。受控回归用显式阈值验证算法不变量；生产默认值在标注集建立后校准。

## 12. Catalog v7 与向量生命周期

Catalog v7 在 `skill_snapshots` 增加：

- `behavior_hash TEXT`；
- `execution_hash TEXT`；
- `hash_algorithm_revision TEXT`。

迁移要求：

- 保留 `content_hash` 和旧 `instruction_hash`；
- v6→v7 只增加可空列，不用旧 `content_hash` 伪造新指纹；
- reconcile 从真实文件重新计算 v2 指纹；
- 当前文件暂时不可用时，新字段保持空并产生可解释 finding；
- 迁移和回填失败必须回滚；
- source staging 直接计算 v2 指纹，不写入虚假回退值。

embedding signature 增加：

```text
<backend>:<model-id>:<model-revision>:d<dimensions>:<kind>:section-<revision>:feature-<revision>
```

旧向量保留用于回滚，但新分析只读取当前签名并在缺失时重建。

现有 `vectors` 表只允许每个 snapshot/model 保存一个向量，无法承载分段通道。Catalog v7 保留该表用于读取历史 run，并新增：

```sql
CREATE TABLE segment_vectors (
    snapshot_id TEXT NOT NULL REFERENCES skill_snapshots(snapshot_id) ON DELETE CASCADE,
    model_signature TEXT NOT NULL,
    backend_kind TEXT NOT NULL,
    channel TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    dimensions INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, model_signature, channel, chunk_index)
);

CREATE INDEX idx_segment_vectors_model
ON segment_vectors(model_signature, channel, snapshot_id);
```

`text_hash` 绑定实际分段文本，避免正文变化后沿用旧 chunk 向量。写入前统一验证向量批次，整个 snapshot 的同签名向量在一个事务中替换，禁止留下部分新、部分旧的通道数据。

## 13. MCP、报告与兼容

- 保留 `skillcheck_analyze`、`skillcheck_evidence`、`skillcheck_save_review`、`skillcheck_save_sync_group` 名称和确认语义；
- `PairSignalsV2` 作为加法字段进入 evidence；
- 报告展示三个指纹关系、分通道分数、coverage 方向和约束极性差异；
- 历史 run 继续按旧 `PairSignals` 读取；
- 新 run 记录 fingerprint、section、feature 和 embedding revisions；
- 新 run 同时记录 vectorizer descriptor、model signature、locality 和对应阈值 profile；
- `MIRRORED_COPY` 继续为 `monitor_only`；
- Agent 继续负责最终语义审查，Skillcheck 不启动第二个 Agent。

## 14. 测试与评估

### 14.1 固定回归集

将实验样本转为仓库内可移植 fixtures，不依赖用户本机 Skill 路径：

- exact copy；
- metadata-only；
- format-only；
- asset-only；
- script-only；
- required/forbidden polarity；
- full/lite containment；
- unrelated pair；
- shared boilerplate false positive；
- CJK、英文和混合语言样本。

确定性验收要求：

- exact copy：三个指纹全部相同；
- metadata/format-only：behavior 与 execution 相同；
- asset-only：只有 package 不同；
- script-only：package、execution 不同，behavior 相同；
- required/forbidden：产生 polarity mismatch；
- shared boilerplate：不得生成 `HIGH_OVERLAP_CANDIDATE`；
- full/lite：必须被候选召回并保留双向 coverage。

向量接口验收还必须覆盖：

- fake backend 的输入顺序、channel 和返回行顺序保持一致；
- 返回行数错误、维度错误、NaN 或 Infinity 时整批拒绝写入；
- 同一 snapshot 的 activation 和多个 procedure chunks 可以并存；
- model signature 改变后旧向量不会被读取；
- 未安装可选本地模型时离线词法通道仍完成分析；
- 未配置 threshold profile 的语义模型只增加候选，不改变自动关系。

### 14.2 标注集门禁

在启用新的生产默认阈值或默认语义模型前，建立不少于 100 组人工标注 Skill 对，至少包含重复、包含、变体、约束差异和无关五类。

发布指标：

- 候选 `Recall@20 ≥ 0.95`；
- 自动 `EXACT_DUPLICATE` 精确率为 1.0；
- `BEHAVIOR_DUPLICATE_CANDIDATE` 精确率不低于 0.98；
- 公共模板困难负样本误判为高重叠的比例不高于 0.02；
- 每个关系类型单独报告 Precision、Recall、F1 和样本数，不用总准确率掩盖少数类别。

这些指标不足时，新模型或新阈值不得成为默认配置，但可保留为显式实验选项。

## 15. 错误处理

- v2 指纹缺失：先 reconcile；仍缺失则保留 Skill 并返回非阻断 finding，不伪造相等关系；
- scripts 文件无法读取：execution hash 标记不可用并返回 evidence，不能使用固定空指纹；
- section 提取失败：保留 activation 与原始正文 evidence，关系降级为人工复核；
- 可选语义模型不可用：继续离线词法分析并明确能力降级；
- backend 返回错误行数、维度、NaN 或 Infinity：拒绝整批写入并返回 `AUDIT002` 类向量 finding；
- 向量签名或维度不一致：拒绝读取并重建，不静默混用；
- 标注集不足：允许固定规则与候选召回上线，不允许未经校准的自动高重叠判定成为默认行为。

## 16. 实施边界

实现按以下顺序推进：

1. 固化回归 fixtures 和评估接口；
2. 实现分层指纹与 Catalog v7；
3. 实现 `SkillSections`、约束极性和模板降权；
4. 实现多通道候选与 `PairSignalsV2`；
5. 改造关系判定、证据和报告；
6. 建立标注集门禁，再比较可选语义模型。

## 17. 实现状态（2026-10-03）

本设计的代码路径已经落地：Catalog v7 分层指纹、分段提取与 polarity/IDF、可插拔本地向量化接口、按签名事务持久化、多通道候选与关系门控、历史证据兼容和离线评估脚本均已完成对应聚焦测试。生产语义模型和阈值仍保持显式实验选项；在完成不少于 100 组人工标注前，不把它们标记为默认校准配置。

前五步必须在默认离线环境可运行。第六步不得阻塞基础版本，也不得未经评估引入默认模型依赖。
