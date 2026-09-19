"""混合检索 + RRF 融合（services 业务编排）。

两路召回 → domain.fusion.fuse 二次融合 → 取回 chunk 原文。
确定性打分器（rerank 槽位预留），无模型依赖，可在无 LLM 下完整验证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import sqlite3

from ..domain.fusion import fuse
from ..domain.types import Chunk
from ..repositories.index_repo import get_chunk, open_indexes


@dataclass(frozen=True)
class RetrievalResult:
    vector: Sequence[tuple[int, float]]
    lexical: Sequence[tuple[int, float]]
    fused: Sequence[tuple[int, float]]
    chunks: dict[int, Chunk]


def retrieve(
    conn: sqlite3.Connection,
    encoder,
    query: str,
    *,
    k_vec: int = 50,
    k_lex: int = 50,
    k_fused: int = 20,
    rerank: Sequence[tuple[int, float]] = (),
    rerank_w: float = 0.5,
) -> RetrievalResult:
    dim = getattr(encoder, "dim", 512)
    vidx, lidx = open_indexes(conn, dim)
    qvec = encoder.encode([query])[0]
    vector = vidx.knn(qvec, k_vec)
    lexical = lidx.search(query, k_lex)
    fused = fuse(lexical, vector, rerank=rerank, w=rerank_w)[:k_fused]
    chunks: dict[int, Chunk] = {}
    for cid, _ in list(vector) + list(lexical):
        if cid not in chunks:
            c = get_chunk(conn, cid)
            if c is not None:
                chunks[cid] = c
    return RetrievalResult(vector=vector, lexical=lexical, fused=fused, chunks=chunks)
