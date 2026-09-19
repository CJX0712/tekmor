"""canonical 序列化：跨语言字节级锁死的单一真相源。

问题背景：JS `JSON.stringify` 默认不转义非 ASCII；Python `json.dumps` 默认
ensure_ascii=True 会转义。若不钉死，同一对象在两语言会算出不同 hash，
破坏 trace 哈希链与黄金向量回归。

裁决（ARCHITECTURE.md §5）：统一 `ensure_ascii=False` + 稳定 key 顺序 + 紧凑分隔符。
aetheros 的 `kernel.test.ts` 对抗性 fixture 原样搬为 Python 黄金向量。
"""

from __future__ import annotations

import json
from typing import Any


def canonical(obj: Any) -> str:
    """返回对象的标准字符串表示（字节级稳定）。

    - ensure_ascii=False：非 ASCII 原样输出（与 TS JSON.stringify 一致）
    - sort_keys=True：稳定 key 顺序
    - 紧凑分隔符：无多余空格
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_bytes(obj: Any) -> bytes:
    """canonical 的 UTF-8 字节形式（用于哈希输入）。"""
    return canonical(obj).encode("utf-8")
