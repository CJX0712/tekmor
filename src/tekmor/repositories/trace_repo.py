"""哈希链轨迹持久化封装（repositories 只存取）。

内存中维护 domain.Trace 用于快速 verify + 180 天留存裁剪；
同时把每帧落盘到 traces 表，作为不可变审计日志。
启动时从 DB 重放重建内存链（哈希确定性，重放可复现）。
"""

from __future__ import annotations

import json
import sqlite3
import time

from ..domain.ser import canonical, canonical_bytes
from ..domain.trace import GENESIS, Trace, TamperDetected, _sha256


class TraceRepo:
    def __init__(self, conn: sqlite3.Connection, retention_days: int = 180) -> None:
        self.conn = conn
        self._mem = Trace(retention_days=retention_days)
        self._reload()

    def _reload(self) -> None:
        rows = self.conn.execute(
            "SELECT kind, payload, ts FROM traces ORDER BY seq"
        ).fetchall()
        for r in rows:
            self._mem.append(r["kind"], json.loads(r["payload"]), r["ts"])

    def append(self, kind: str, payload: dict, now: int | None = None) -> dict:
        span = self._mem.append(kind, payload, now)
        self.conn.execute(
            "INSERT OR REPLACE INTO traces(seq, kind, payload, prev_hash, ts, hash) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (span.seq, span.kind, canonical(span.payload), span.prev_hash, span.ts, span.hash),
        )
        self.conn.commit()
        return {"seq": span.seq, "hash": span.hash}

    def verify(self) -> bool:
        return self._mem.verify()

    def verify_db(self) -> bool:
        rows = self.conn.execute(
            "SELECT seq, kind, payload, prev_hash, ts, hash FROM traces ORDER BY seq"
        ).fetchall()
        expected_prev = GENESIS
        expected_seq = 1
        for r in rows:
            if r["prev_hash"] != expected_prev:
                raise TamperDetected(f"db seq={r['seq']} prev 不匹配")
            if r["seq"] != expected_seq:
                raise TamperDetected(f"db seq 不连续：{r['seq']} != {expected_seq}")
            recomputed = _sha256(canonical_bytes({
                "seq": r["seq"], "kind": r["kind"],
                "payload": json.loads(r["payload"]),
                "prev": r["prev_hash"], "ts": r["ts"],
            }))
            if recomputed != r["hash"]:
                raise TamperDetected(f"db seq={r['seq']} hash 重算不匹配")
            expected_prev = r["hash"]
            expected_seq += 1
        return True

    def prune_before(self, cutoff_ts: int) -> int:
        return self._mem.prune_before(cutoff_ts)

    def __len__(self) -> int:
        return len(self._mem)
