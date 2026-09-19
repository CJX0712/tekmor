"""哈希链 append-only 轨迹（AC-09 载体），修复版。

移植并修复 aetheros 内核缺陷：原实现中 "180 天留存地板(prune)" 与
"防篡改校验(verify)" 互斥——prune 之后链的 prev 指针断裂，verify 失败。

修复策略（与 aetheros commit a1fef02 一致）：
- 引入 `pruned_anchor`（prune 截断点处最后一帧的 hash）与 `pruned_count`（被截断帧数）。
- `verify()` 的 genesis 判定改为 `prev == self.pruned_anchor`；seq 连续性校验改为
  `self.pruned_count + i + 1`，使 prune 后链仍可端到端验证（AC-09 可重建）。
- `prune_before(cutoff_ts)` 不删除、只把截断点前一帧设为新 anchor，链永不断路。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from .ser import canonical_bytes

GENESIS = "genesis"


class TamperDetected(Exception):
    """哈希链完整性被破坏。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"tamper-detected: {reason}")
        self.reason = reason


@dataclass
class TraceSpan:
    seq: int
    kind: str
    payload: dict[str, Any]
    prev_hash: str
    ts: int
    hash: str = field(default="")


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Trace:
    """可审计的 append-only 轨迹哈希链。"""

    def __init__(self, retention_days: int = 180) -> None:
        self.retention_days = retention_days
        self._spans: list[TraceSpan] = []
        self._pruned_anchor: str = GENESIS
        self._pruned_count: int = 0

    # ----- 写入 -----
    def append(self, kind: str, payload: dict[str, Any], now: int | None = None) -> TraceSpan:
        seq = self._pruned_count + len(self._spans) + 1
        prev = self._pruned_anchor if not self._spans else self._spans[-1].hash
        ts = int(now if now is not None else time.time())
        h = _sha256(canonical_bytes({
            "seq": seq,
            "kind": kind,
            "payload": payload,
            "prev": prev,
            "ts": ts,
        }))
        span = TraceSpan(seq=seq, kind=kind, payload=payload, prev_hash=prev, ts=ts, hash=h)
        self._spans.append(span)
        return span

    # ----- 校验 -----
    def verify(self) -> bool:
        """端到端校验整链完整性。失败抛 TamperDetected。"""
        expected_prev = self._pruned_anchor
        expected_seq = self._pruned_count + 1
        for s in self._spans:
            if s.prev_hash != expected_prev:
                raise TamperDetected(
                    f"seq={s.seq} prev 期望 {expected_prev[:8]} 实际 {s.prev_hash[:8]}"
                )
            if s.seq != expected_seq:
                raise TamperDetected(f"seq 不连续：期望 {expected_seq} 实际 {s.seq}")
            recomputed = _sha256(canonical_bytes({
                "seq": s.seq,
                "kind": s.kind,
                "payload": s.payload,
                "prev": s.prev_hash,
                "ts": s.ts,
            }))
            if recomputed != s.hash:
                raise TamperDetected(f"seq={s.seq} hash 重算不匹配")
            expected_prev = s.hash
            expected_seq += 1
        return True

    def is_intact(self) -> bool:
        try:
            return self.verify()
        except TamperDetected:
            return False

    # ----- 留存/裁剪（AC-09：截断不断路）-----
    def prune_before(self, cutoff_ts: int) -> int:
        """删除 cutoff_ts 之前的帧，但保留截断点 anchor，链仍可验证。

        Returns:
            被截断的帧数。
        """
        if not self._spans:
            return 0
        idx = 0
        while idx < len(self._spans) and self._spans[idx].ts < cutoff_ts:
            idx += 1
        if idx == 0:
            return 0
        self._pruned_anchor = self._spans[idx - 1].hash
        self._pruned_count += idx
        self._spans = self._spans[idx:]
        return idx

    def __len__(self) -> int:
        return len(self._spans)
