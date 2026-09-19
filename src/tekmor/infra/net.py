"""出站流量计数（AC-01 载体）。

全链路真实计数（非硬编码 0）：任何外部网络调用前必须调用 record_outbound，
get_outbound() 返回累计值。offline-guard 在断网测试中断言其恒为 0。
"""

from __future__ import annotations

import threading


class _Counter:
    def __init__(self) -> None:
        self._out = 0
        self._lock = threading.Lock()

    def count(self, n: int = 1) -> None:
        with self._lock:
            self._out += n

    def value(self) -> int:
        with self._lock:
            return self._out


_net = _Counter()


def record_outbound(n: int = 1) -> None:
    """记录一次出站请求（由 infra 各外部适配器调用）。"""
    if n < 0:
        raise ValueError("n 必须 >= 0")
    _net.count(n)


def get_outbound() -> int:
    """返回真实累计出站请求数（AC-01 审计）。"""
    return _net.value()


def reset_outbound() -> None:
    """测试隔离用：清零计数器。"""
    _net.count(-_net.value())
