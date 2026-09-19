"""证据闸门与段落级证据切片（AC-04/05/06 载体）。

- EvidenceGate：claim 无 anchor（无证据）时，strict 默认拦截（AC-05）。
- verify_citation：citation 解析到的 chunk 是否真正支撑该 claim（AC-06 启发式）。
- slice_evidence：byte↔utf16 双区间交叉校验，取回原文锚定片段（AC-04）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .types import Claim, EvidenceAnchor, EvidenceMode

# ASCII 词（小写）；CJK 单字单独成特征（中文无空格分词，须字符级）
_WORD_RE = re.compile(r"[a-z0-9]+", re.UNICODE)


def _features(text: str) -> set[str]:
    f: set[str] = set(_WORD_RE.findall(text.lower()))
    for ch in text:
        if "一" <= ch <= "鿿":  # CJK 统一表意文字
            f.add(ch)
    return f


@dataclass(frozen=True)
class GateOutcome:
    passed: tuple[Claim, ...]
    blocked: tuple[Claim, ...]
    mode: EvidenceMode


class EvidenceGate:
    """证据闸门：决定哪些 claim 可以呈现。"""

    def __init__(self, mode: EvidenceMode = EvidenceMode.STRICT) -> None:
        self.mode = mode

    def gate(self, claims: Iterable[Claim]) -> GateOutcome:
        passed: list[Claim] = []
        blocked: list[Claim] = []
        for c in claims:
            if c.anchor is None:
                if self.mode == EvidenceMode.STRICT:
                    blocked.append(c)  # AC-05：无证据不输出
                else:
                    passed.append(c)   # lenient：放行但 trace 永久标记 lenient (AC-14)
            else:
                passed.append(c)
        return GateOutcome(tuple(passed), tuple(blocked), self.mode)


def verify_citation(claim: Claim, chunk_text: str, threshold: float = 0.2) -> bool:
    """判断 anchor 指向的 chunk 是否支撑 claim（AC-06 启发式）。

    用 claim 与锚定片段的 token 重叠率做轻量校验。重叠率低于阈值视为
    "citation-unverified"——该 claim 不应被呈现实为 grounded。

    Args:
        claim: 待校验主张（须有 anchor）
        chunk_text: 该 anchor 所属 chunk 的完整原文
        threshold: 最小重叠率

    Returns:
        True 表示证据可信；False 表示 citation-unverified。
    """
    if claim.anchor is None:
        return False
    a = claim.anchor
    span = chunk_text[a.byte_start:a.byte_end]
    if not span.strip():
        return False
    claim_feats = _features(claim.text)
    if not claim_feats:
        return False
    span_feats = _features(span)
    if not span_feats:
        return False
    overlap = len(claim_feats & span_feats) / len(claim_feats)
    return overlap >= threshold


def slice_evidence(anchor: EvidenceAnchor, chunk_text: str) -> str:
    """按 byte↔utf16 双区间交叉校验，返回锚定原文片段（AC-04）。

    Raises:
        ValueError: 任一区间越界，或 byte 切片与 utf16 切片不一致（篡改/偏移错位）。
    """
    raw = chunk_text.encode("utf-8")
    u16 = chunk_text.encode("utf-16-le")

    if not (0 <= anchor.byte_start <= anchor.byte_end <= len(raw)):
        raise ValueError("byte 区间越界")
    if not (0 <= anchor.utf16_start <= anchor.utf16_end <= len(u16) // 2):
        raise ValueError("utf16 区间越界")

    byte_slice = raw[anchor.byte_start:anchor.byte_end].decode("utf-8")
    utf16_slice = chunk_text[anchor.utf16_start:anchor.utf16_end]

    if byte_slice != utf16_slice:
        raise ValueError("byte 切片与 utf16 切片不一致（偏移错位或被篡改）")

    return byte_slice
