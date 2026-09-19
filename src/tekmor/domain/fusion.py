"""RRF 二次融合（AC-06/07/08 不变量载体）。

设计要点：
- 第一阶：lexical + semantic 两路做 RRF，得到 base 分。
- rerank（若有）：作为**第三路信号**以权重 w 融合进 base（AC-07），而非直接采用重排顺序。
- 结构不变量：w 必须严格 < 1（AC-08）。这使得即便注入"全倒序 reranker"，
  第一阶融合冠军仍保持 top-1（base 分差 > w 带来的重排惩罚），杜绝被劣质重排器反向操控。
"""

from __future__ import annotations

from typing import Iterable, Sequence

# RRF 常数
RRF_K: int = 60
# rerank 作为第三路信号的权重（必须 < 1）
RERANK_WEIGHT: float = 0.5
# 主优先级：平局时偏好出现在更多列表中的条目
PRIMARY_PRIORITY: int = 2

# RankList 约定：元素为 (item_id, score)，按排名顺序（索引=rank）排列。
RankList = Sequence[tuple[int, float]]


def rrf_score(rank: int, k: int = RRF_K) -> float:
    """第 rank 名（0-based）的 RRF 分数。"""
    if rank < 0:
        raise ValueError("rank 必须 >= 0")
    return 1.0 / (k + rank + 1)  # +1 使 rank0 -> 1/(k+1)


def _accumulate(ranklists: Iterable[RankList], k: int = RRF_K) -> dict[int, float]:
    scores: dict[int, float] = {}
    counts: dict[int, int] = {}
    for rl in ranklists:
        for rank, (item_id, _score) in enumerate(rl):
            scores[item_id] = scores.get(item_id, 0.0) + rrf_score(rank, k)
            counts[item_id] = counts.get(item_id, 0) + 1
    return scores, counts


def fuse(
    lexical: RankList,
    semantic: RankList,
    rerank: RankList = (),
    w: float = RERANK_WEIGHT,
) -> list[tuple[int, float]]:
    """融合多路召回为排序结果。

    Args:
        lexical: 词法召回（FTS5 trigram）排名列表
        semantic: 向量召回（sqlite-vec KNN）排名列表
        rerank: 重排器输出（顺序即排名）。若非空，作为第三路信号按 w 融合。
        w: rerank 融合权重，必须落在 [0, 1)。

    Returns:
        排序后的 [(item_id, fused_score), ...]（分数降序，平局按出现列表数、id 升序）。

    Raises:
        ValueError: w 不在 [0,1)（AC-08 结构守卫）。
    """
    if not (0.0 <= w < 1.0):
        raise ValueError(f"rerank 权重 w 必须严格 < 1（AC-08），收到 w={w}")

    # 第一阶融合
    scores, counts = _accumulate([lexical, semantic])

    # 第三路信号：rerank 作为额外 RRF 贡献，绝不直接覆盖 base
    if rerank:
        rerank_scores, _ = _accumulate([rerank])
        for item_id, base in scores.items():
            scores[item_id] = base + w * rerank_scores.get(item_id, 0.0)

    # 排序：分数降序；平局按 (出现列表数 desc, id asc)
    ranked = sorted(
        scores.items(),
        key=lambda kv: (-kv[1], -counts.get(kv[0], 0), kv[0]),
    )
    return ranked


def top_k(ranked: list[tuple[int, float]], k: int) -> list[int]:
    """取前 k 个 item_id。"""
    return [item_id for item_id, _ in ranked[:k]]
