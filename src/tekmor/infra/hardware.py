"""硬件探测与线程钳制（AC-02/03 载体）。

auto_threads 是纯函数，可在无 psutil 环境下直接单测（钳制规则与实测一致：
4 线程 32.5 tok/s > 16 线程 8.2 tok/s，故钳到上界 4；下界 2 防止单线程吞吐塌缩）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# 线程钳制硬边界（AC-02/03）
THREAD_MIN = 2
THREAD_MAX = 4


@dataclass(frozen=True)
class HardwareProfile:
    total_bytes: int
    avail_bytes: int
    threads: int  # 已钳到 [THREAD_MIN, THREAD_MAX]


class InsufficientMemory(Exception):
    """载入大模型前的内存护栏（AC-14 韧性）。"""


def auto_threads(n: int | None = None) -> int:
    """把任意线程数钳制到 [THREAD_MIN, THREAD_MAX]（AC-02/03）。

    - 未指定：取 min(cpu_count, THREAD_MAX) 再与 THREAD_MIN 取大。
    - 指定：直接与边界 clamp。
    任何改动使返回落在区间外 → 调用方单测具名失败（AC-03）。
    """
    if n is None:
        try:
            n = os.cpu_count() or THREAD_MIN
        except Exception:
            n = THREAD_MIN
    clamped = max(THREAD_MIN, min(THREAD_MAX, int(n)))
    return clamped


def detect() -> HardwareProfile:
    """探测硬件画像。优先 psutil，缺失时降级到保守值。"""
    total = 0
    avail = 0
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        total = vm.total
        avail = vm.available
    except Exception:
        # 降级：未知环境下给保守估计，避免误判放行
        total = 0
        avail = 0
    return HardwareProfile(
        total_bytes=total,
        avail_bytes=avail,
        threads=auto_threads(),
    )


def require_free(p: HardwareProfile, need_bytes: int) -> None:
    """载入 LLM 前护栏：空闲不足则抛 InsufficientMemory（不 OOM 崩进程，AC-14）。"""
    if p.avail_bytes > 0 and p.avail_bytes < need_bytes:
        raise InsufficientMemory(
            f"空闲内存 {p.avail_bytes/1e9:.2f}GB < 需求 {need_bytes/1e9:.2f}GB"
        )
