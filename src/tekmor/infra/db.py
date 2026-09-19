"""SQLite 连接 / FTS5 + sqlite-vec 加载 / 迁移（infra 叶子层）。

- FTS5 `tokenize='trigram'`：中文子串命中（unicode61 中文 0 命中，已实测证伪）。
- sqlite-vec：向量索引（vec0）。本机若未 `uv sync` 装 wheel，connect 会给出明确指引。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

try:  # sqlite-vec 为可选依赖（预编译 wheel）
    import sqlite_vec  # type: ignore
except Exception:  # noqa: BLE001
    sqlite_vec = None  # 仅在 connect 时按需报错


def connect(db_path: str | Path) -> sqlite3.Connection:
    """打开 SQLite 连接并加载 sqlite-vec 与 FTS5 扩展。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if sqlite_vec is not None:
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "sqlite-vec 加载失败，请运行 `uv sync` 安装预编译 wheel (sqlite-vec==0.1.9)"
            ) from e
    else:
        # 仍然允许 FTS5（内置）；vec0 在 migrate 时再报错指引
        pass
    return conn


def migrate(conn: sqlite3.Connection, dim: int) -> None:
    """创建表结构：docs / chunks / lexical(FTS5 trigram) / vec(sqlite-vec) / traces。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS docs (
            id          TEXT PRIMARY KEY,
            path        TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            mtime       REAL NOT NULL,
            updated_at  INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id      TEXT NOT NULL,
            text        TEXT NOT NULL,
            byte_start  INTEGER NOT NULL,
            byte_end    INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(
            text, doc_id UNINDEXED, chunk_id UNINDEXED, tokenize='trigram'
        );
        CREATE TABLE IF NOT EXISTS traces (
            seq         INTEGER PRIMARY KEY,
            kind        TEXT NOT NULL,
            payload     TEXT NOT NULL,
            prev_hash   TEXT NOT NULL,
            ts          INTEGER NOT NULL,
            hash        TEXT NOT NULL
        );
        """
    )
    # vec(sqlite-vec) 在 repositories.open_indexes 中按可用性动态创建
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """清空所有索引（开发/测试用）。"""
    conn.executescript(
        "DELETE FROM docs; DELETE FROM chunks; DELETE FROM lexical; DELETE FROM vec; DELETE FROM traces;"
    )
    conn.commit()
