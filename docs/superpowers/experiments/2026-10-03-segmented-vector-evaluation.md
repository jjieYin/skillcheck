# 分段向量关系评估记录

## 目的

本评估脚本验证新的分段表示、分通道候选召回和关系门控是否保持可解释边界。它只读取仓库内 `tests/fixtures/fingerprints`，不创建或修改 Catalog，也不写入用户 Skill。

运行：

```text
PYTHONPATH=src python scripts/experiments/segmented_vector_evaluation.py \
  --fixture-dir tests/fixtures/fingerprints --format markdown
```

默认使用离线 `lexical_hash`，不依赖网络或本地模型。需要实验性本地语义模型时，必须显式指定 `--backend sentence-transformers --model-id ...`；模型不可用时脚本返回 `unavailable`，不会把 hash 回退伪装成语义结果。

## 固定样本

样本覆盖 exact copy、metadata/format/asset 差异、脚本实现变体、required/forbidden 极性、full/lite 包含、无关样本、公共模板困难负样本。输出按关系分别给出 precision、recall、F1 和 support，同时给出 Recall@20 与公共模板误报率。

当前固定样本用于回归和算法不变量检查，不代表生产阈值已经校准。启用新的语义模型或生产默认阈值前，仍需要至少 100 组人工标注 Skill 对，并分别满足：候选 Recall@20 ≥ 0.95、exact duplicate precision = 1.0、behavior duplicate precision ≥ 0.98、公共模板高重叠误报率 ≤ 0.02。

## 解释边界

- `semantic_similarity` 只记录真实语义模型通道；离线 hash 结果保存在 `hashed_lexical_similarity`。
- 未绑定 `threshold_profile` 的语义模型只增加候选召回，不能自动产生高重叠关系。
- `CONSTRAINT_MISMATCH_CANDIDATE` 表示极性差异需要人工审查，不等同于最终冲突。
- 向量签名包含模型、维度、分段和特征版本；更换任一项都必须重建对应分段向量。
