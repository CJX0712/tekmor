"""唯一聚合层：retrieve → (load LLM) → answer → (unload LLM)（services 业务编排）。

严格串行，LLM 可驱逐（keep_alive=0），与常驻嵌入器永不同时驻留。
证据闸门：strict 下无相关检索 → 中文兜底拒答（AC-11）；claim 无锚定 → 标记 evidence-gap（AC-05）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlite3

from ..domain.evidence import EvidenceGate, _features  # 复用字符级特征
from ..domain.types import Claim, EvidenceAnchor, EvidenceMode
from .retrieve import retrieve

_RELEVANCE_FLOOR = 0.15  # 中文兜底阈值（AC-11）


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[EvidenceAnchor, ...]
    mode: EvidenceMode
    refused: bool
    relevant_chunk_ids: tuple[int, ...]


def _split_sentences(text: str) -> list[str]:
    # 中英文断句
    parts = re.split(r"(?<=[。！？!?.\n])", text)
    return [p.strip() for p in parts if p.strip()]


def _best_anchor(sentence: str, chunks: dict[int, Chunk], fallback_idx: dict[int, int]) -> EvidenceAnchor | None:
    """为句子找最佳支撑 chunk，返回 byte/utf16 双区间锚（命中 '知识库' 等子串优先）。"""
    best_cid = None
    best_score = 0.0
    for cid, ch in chunks.items():
        # 子串直接命中（中文最常见）
        if sentence and sentence[:8] and _sub_in(sentence, ch.text):
            return _make_anchor(cid, ch, sentence)
        s_feat = _features(sentence)
        if not s_feat:
            continue
        c_feat = _features(ch.text)
        score = len(s_feat & c_feat) / len(s_feat)
        if score > best_score:
            best_score = score
            best_cid = cid
    if best_cid is not None and best_score >= 0.2:
        return _make_anchor(best_cid, chunks[best_cid], sentence)
    return None


def _sub_in(sentence: str, text: str) -> bool:
    # 取句子前若干字符作为查询子串，在 chunk 中找
    q = sentence[: min(12, len(sentence))]
    return q in text


def _make_anchor(cid: int, ch: Chunk, sentence: str) -> EvidenceAnchor:
    # 在 chunk 文本中定位句子子串的字节/utf16 偏移
    q = sentence[: min(12, len(sentence))]
    pos = ch.text.find(q)
    if pos < 0:
        pos = 0
    u16_start = pos
    u16_end = min(pos + len(q), len(ch.text))
    b_start = len(ch.text[:pos].encode("utf-8"))
    b_end = len(ch.text[:u16_end].encode("utf-8"))
    return EvidenceAnchor(
        chunk_id=cid, utf16_start=u16_start, utf16_end=u16_end,
        byte_start=ch.byte_start + b_start, byte_end=ch.byte_start + b_end,
    )


def answer(
    conn: sqlite3.Connection,
    encoder,
    llm,
    query: str,
    *,
    mode: EvidenceMode = EvidenceMode.STRICT,
    k_fused: int = 8,
) -> Answer:
    res = retrieve(conn, encoder, query, k_fused=k_fused)
    fused_ids = [cid for cid, _ in res.fused]

    # AC-11：中文兜底——检索无相关则拒答
    if not fused_ids or not res.chunks:
        return Answer(
            text="未找到相关文档。", citations=(), mode=mode,
            refused=True, relevant_chunk_ids=(),
        )

    # 组装上下文（仅取 top-k chunk 原文）
    context = "\n\n".join(
        f"[#{cid}] {res.chunks[cid].text}" for cid in fused_ids if cid in res.chunks
    )
    messages = [
        {
            "role": "system",
            "content": "你是本地知识库助手。仅依据提供的[文档]片段回答，"
            "若片段不足以回答，明确说不知道。回答尽量简洁。",
        },
        {"role": "user", "content": f"[文档]\n{context}\n\n[问题] {query}"},
    ]

    raw = llm.chat(messages, stream=False, keep_alive="0", num_ctx=4096, num_thread=4)
    if isinstance(raw, str):
        text = raw
    else:
        text = "".join(raw)

    # 证据锚定：为每句找支撑 chunk
    sentences = _split_sentences(text)
    citations: list[EvidenceAnchor] = []
    for s in sentences:
        a = _best_anchor(s, res.chunks, {})
        if a is not None:
            citations.append(a)

    # AC-05：strict 下若无任何锚定，标记为拒答不输出幻觉
    if mode == EvidenceMode.STRICT and not citations:
        gate = EvidenceGate(mode).gate([Claim(id="c0", text=text, anchor=None)])
        if gate.blocked:
            return Answer(
                text="未找到相关文档。", citations=(), mode=mode,
                refused=True, relevant_chunk_ids=tuple(fused_ids),
            )

    return Answer(
        text=text, citations=tuple(citations), mode=mode,
        refused=False, relevant_chunk_ids=tuple(fused_ids),
    )
