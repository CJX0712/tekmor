"""Tekmor — 本地优先、端到端可验证的 RAG 知识库与证据锚定平台。

作者：晨星
设计继承 aetheros 的设计系统与内核思路（aetheros 仅作只读参考源）。
本包采用窄移植策略：fusion / evidence / trace 等算法核心从 aetheros(TS) 移植到 Python，
并修复了 aetheros 内核中 pruneBefore 与防篡改校验互斥的缺陷（见 domain/trace.py）。
"""

__version__ = "0.1.0"
__author__ = "晨星"
