"""领域类型定义（叶子层，纯类型，零依赖）。

与 aetheros 的 canonical 序列化字节级对齐：所有跨语言序列化必须经过
`tekmor.domain.ser.canonical`（ensure_ascii=False + 稳定 key 顺序），
否则 TS 与 Python 会算出不同 hash。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence


@dataclass(frozen=True)
class Chunk:
    """一段被切分的原文。byte_* 为 UTF-8 字节偏移，用于证据锚定。"""

    id: int
    doc_id: str
    text: str
    byte_start: int
    byte_end: int


@dataclass(frozen=True)
class EvidenceAnchor:
    """证据锚：把 claim 绑定到原文的一段（byte + utf16 双区间交叉校验）。"""

    chunk_id: int
    utf16_start: int
    utf16_end: int
    byte_start: int
    byte_end: int


@dataclass(frozen=True)
class Claim:
    """模型生成的一个主张。anchor 为 None 表示无证据支撑。"""

    id: str
    text: str
    anchor: EvidenceAnchor | None = None


class EvidenceMode(StrEnum):
    """证据模式。LENIENT 仅可显式开启，且每条 trace 永久标记（AC-14）。"""

    STRICT = "strict"
    LENIENT = "lenient"


@dataclass(frozen=True)
class RunInput:
    query: str
    mode: EvidenceMode = EvidenceMode.STRICT


@dataclass(frozen=True)
class RunResult:
    answer: str
    citations: tuple[EvidenceAnchor, ...]
    mode: EvidenceMode
    refused: bool
