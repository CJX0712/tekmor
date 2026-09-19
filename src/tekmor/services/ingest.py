"""文档解析切片 + 增量 hash 检测 + 写索引（services 业务编排）。

AC-10：文档内容 hash 未变 → 跳过重嵌。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import sqlite3


@dataclass
class IngestReport:
    doc_id: str
    path: str
    chunks: int
    new_chunks: int
    skipped: bool  # 因内容未变而跳过（AC-10）


def read_text(path: Path) -> str:
    """读取文档纯文本。支持 txt/md/json；pdf 在 pypdf 可用时支持。"""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md", ".json"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(str(path))
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"PDF 解析失败（需 pypdf）：{e}")
    raise RuntimeError(f"不支持的扩展名：{suffix}")


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[tuple[str, int, int]]:
    """按字符滑动窗口切片（中文友好）。返回 (片段, byte_start, byte_end)。"""
    out: list[tuple[str, int, int]] = []
    raw = text.encode("utf-8")
    step = max(1, chunk_size - overlap)
    i = 0
    n = len(text)
    while i < n:
        seg = text[i : i + chunk_size]
        b_start = len(text[:i].encode("utf-8"))
        b_end = b_start + len(seg.encode("utf-8"))
        out.append((seg, b_start, b_end))
        if i + chunk_size >= n:
            break
        i += step
    return out


def ingest_file(
    conn: sqlite3.Connection,
    encoder,
    path: str | Path,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
) -> IngestReport:
    p = Path(path)
    doc_id = p.resolve().as_posix()
    text = read_text(p)
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    existing = conn.execute(
        "SELECT content_hash FROM docs WHERE id = ?", (doc_id,)
    ).fetchone()
    if existing is not None and existing["content_hash"] == content_hash:
        return IngestReport(doc_id, str(p), 0, 0, skipped=True)  # AC-10

    # 移除旧切片
    old = [r["id"] for r in conn.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,)).fetchall()]
    for cid in old:
        conn.execute("DELETE FROM vec WHERE rowid = ?", (cid,))
        conn.execute("DELETE FROM lexical WHERE chunk_id = ?", (cid,))
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))

    chunks = chunk_text(text, chunk_size, overlap)
    conn.execute(
        "INSERT INTO docs(id, path, content_hash, mtime, updated_at) VALUES(?, ?, ?, ?, ?)",
        (doc_id, str(p), content_hash, p.stat().st_mtime, int(time.time())),
    )

    from ..infra.db import reset  # noqa: F401  (确保迁移已完成)
    from ..repositories.index_repo import LexicalIndex, VectorIndex, open_indexes

    vidx, lidx = open_indexes(conn, getattr(encoder, "dim", 512))
    texts = [c[0] for c in chunks]
    vecs = encoder.encode(texts)
    for (seg, b_start, b_end), vec in zip(chunks, vecs):
        cur = conn.execute(
            "INSERT INTO chunks(doc_id, text, byte_start, byte_end) VALUES(?, ?, ?, ?)",
            (doc_id, seg, b_start, b_end),
        )
        cid = cur.lastrowid
        vidx.upsert(cid, vec)
        lidx.upsert(cid, doc_id, seg)
    conn.commit()
    return IngestReport(doc_id, str(p), len(chunks), len(chunks), skipped=False)
