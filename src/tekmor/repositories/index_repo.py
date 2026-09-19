"""向量索引（sqlite-vec）+ 词法索引（FTS5 trigram）的 upsert/knn/search。

repositories 只做存取；融合/业务判断在 services/retrieve 与 domain/fusion。

向量主路径 = sqlite-vec(vec0)。若 vec0 不可用（如未 `uv sync`），自动降级到
进程内纯 Python 余弦索引（仅兜底，不引入任何第三方包），保证链路可运行（AC-13 降级精神）。
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

from ..domain.types import Chunk

RankList = Sequence[tuple[int, float]]

# 兜底向量按连接缓存。sqlite3.Connection 不可挂属性、不可弱引用，
# 故用 id(conn) 作键，并保留强引用防止 id 复用冲突（仅兜底路径使用）。
_PURE_STORE: dict[int, dict[int, list[float]]] = {}
_PURE_CONNS: dict[int, sqlite3.Connection] = {}


def _to_blob(vec) -> bytes:  # vec 为可迭代浮点序列
    import numpy as np

    return np.ascontiguousarray(vec, dtype=np.float32).tobytes()


def _vec0_available(conn: sqlite3.Connection, dim: int) -> bool:
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS _vec_probe USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
        )
        conn.execute("DROP TABLE IF EXISTS _vec_probe")
        return True
    except Exception:  # noqa: BLE001
        return False


class VectorIndex:
    """主路径：sqlite-vec vec0 KNN。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, chunk_id: int, vec) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO vec(rowid, embedding) VALUES(?, ?)",
            (chunk_id, _to_blob(vec)),
        )

    def knn(self, query_vec, k: int) -> RankList:
        rows = self.conn.execute(
            "SELECT rowid, distance FROM vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (_to_blob(query_vec), k),
        ).fetchall()
        return [(r["rowid"], float(r["distance"])) for r in rows]


class PureVectorIndex:
    """兜底路径：进程内纯 Python 余弦（无 numpy / 无 sqlite-vec 依赖）。

    向量挂在连接对象上，确保同一连接的 ingest→retrieve 之间不丢失。
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        _PURE_CONNS[id(conn)] = conn
        self._store = _PURE_STORE.setdefault(id(conn), {})

    def upsert(self, chunk_id: int, vec) -> None:
        self._store[chunk_id] = [float(x) for x in vec]

    def knn(self, query_vec, k: int) -> RankList:
        q = [float(x) for x in query_vec]
        qn = sum(x * x for x in q) ** 0.5 or 1.0
        scored = []
        for cid, v in self._store.items():
            dot = sum(a * b for a, b in zip(q, v))
            vn = sum(x * x for x in v) ** 0.5 or 1.0
            cos = dot / (qn * vn)
            scored.append((cid, 1.0 - cos))  # 距离 = 1 - cos
        scored.sort(key=lambda x: x[1])
        return scored[:k]


class LexicalIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, chunk_id: int, doc_id: str, text: str) -> None:
        self.conn.execute(
            "INSERT INTO lexical(rowid, text, doc_id, chunk_id) VALUES(?, ?, ?, ?)",
            (chunk_id, text, doc_id, chunk_id),
        )

    def search(self, query: str, k: int) -> RankList:
        rows = self.conn.execute(
            "SELECT chunk_id FROM lexical WHERE lexical MATCH ? ORDER BY rank LIMIT ?",
            (query, k),
        ).fetchall()
        return [(r["chunk_id"], 0.0) for r in rows]


def open_indexes(conn: sqlite3.Connection, dim: int) -> tuple["VectorIndex | PureVectorIndex", LexicalIndex]:
    use_vec0 = _vec0_available(conn, dim)
    if use_vec0:
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
            )
            conn.commit()
            vector = VectorIndex(conn)
        except Exception:  # noqa: BLE001
            vector = PureVectorIndex(conn)
    else:
        vector = PureVectorIndex(conn)
    return vector, LexicalIndex(conn)


def get_chunk(conn: sqlite3.Connection, chunk_id: int) -> Chunk | None:
    r = conn.execute(
        "SELECT id, doc_id, text, byte_start, byte_end FROM chunks WHERE id = ?",
        (chunk_id,),
    ).fetchone()
    if r is None:
        return None
    return Chunk(
        id=r["id"], doc_id=r["doc_id"], text=r["text"],
        byte_start=r["byte_start"], byte_end=r["byte_end"],
    )
