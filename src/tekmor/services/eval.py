"""评估：黄金向量回归 / 命中率 / 拒答率 / 延迟（services 业务编排）。

核心命中率（hit@k）只依赖 retrieve，可在无 LLM 下完整验证；
拒答率 / 延迟可选依赖 LLM。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import sqlite3


@dataclass
class Golden:
    query: str
    relevant: list[int]  # 期望命中的 chunk_id
    expect_refusal: bool = False


@dataclass
class EvalReport:
    total: int
    hit_at_3: float
    hit_at_5: float
    refusal_rate: float
    latency_ms: float
    details: list[dict] = field(default_factory=list)


def load_golden(path: str | Path) -> list[Golden]:
    p = Path(path)
    out: list[Golden] = []
    if p.suffix == ".jsonl":
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                out.append(Golden(o["query"], o["relevant"], o.get("expect_refusal", False)))
    else:
        o = json.loads(p.read_text(encoding="utf-8"))
        for item in o:
            out.append(Golden(item["query"], item["relevant"], item.get("expect_refusal", False)))
    return out


def run_golden(
    conn: sqlite3.Connection,
    encoder,
    goldens: list[Golden],
    *,
    k_fused: int = 5,
) -> EvalReport:
    from .retrieve import retrieve

    hits3 = 0
    hits5 = 0
    refusals = 0
    lat = 0.0
    details = []
    for g in goldens:
        t0 = time.time()
        res = retrieve(conn, encoder, g.query, k_fused=k_fused)
        dt = (time.time() - t0) * 1000.0
        lat += dt
        ids = [cid for cid, _ in res.fused]
        top3 = set(ids[:3])
        top5 = set(ids[:5])
        h3 = bool(top3 & set(g.relevant))
        h5 = bool(top5 & set(g.relevant))
        hits3 += int(h3)
        hits5 += int(h5)
        if g.expect_refusal and not res.fused:
            refusals += 1
        details.append({
            "query": g.query, "hit@3": h3, "hit@5": h5,
            "relevant": g.relevant, "got": ids[:5],
        })
    n = max(1, len(goldens))
    return EvalReport(
        total=len(goldens),
        hit_at_3=hits3 / n,
        hit_at_5=hits5 / n,
        refusal_rate=refusals / n,
        latency_ms=lat / n,
        details=details,
    )
