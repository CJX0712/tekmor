"""集成测试：ingest → retrieve → cite 端到端（可在无 sqlite-vec/numpy 环境运行）。

使用 FakeEmbedder（字符袋向量，确定性）与内存 SQLite（FTS5 trigram 内置可用，
vec0 不可用时自动降级纯 Python 余弦），验证 F2 混合检索 + F3 证据链编排、AC-10 增量索引。
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tekmor.infra.db import connect, migrate  # noqa: E402
from tekmor.services.ingest import IngestReport, ingest_file  # noqa: E402
from tekmor.services.retrieve import retrieve  # noqa: E402


class FakeEmbedder:
    """确定性字符袋嵌入器（仅测试用，不依赖 onnxruntime）。"""

    dim = 8

    def encode(self, texts, *, batch: int = 8):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for ch in t:
                vec[ord(ch) % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


def _ok(name: str) -> None:
    print(f"  PASS  {name}")


def test_ingest_and_retrieve():
    conn = connect(":memory:")
    migrate(conn, 8)
    enc = FakeEmbedder()

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("Tekmor 使用 SQLite FTS5 的 trigram 分词器处理中文子串检索。\n")
        f.write("Tekmor 的 CPU 推理线程被钳制在 2 到 4 之间。\n")
        path = f.name
    try:
        rep = ingest_file(conn, enc, path, chunk_size=64, overlap=8)
        assert isinstance(rep, IngestReport)
        assert rep.chunks >= 1, "应至少切出一个 chunk"
        # 检索：用原文子串查询，期望命中相关 chunk
        res = retrieve(conn, enc, "trigram 分词器", k_fused=5)
        assert len(res.fused) >= 1, "应召回至少 1 个 chunk"
        assert len(res.chunks) >= 1
        top_id = res.fused[0][0]
        assert top_id in res.chunks
        _ok(f"ingest+retrieve 端到端 (top chunk #{top_id})")

        # AC-10：再次导入同内容 → 跳过
        rep2 = ingest_file(conn, enc, path, chunk_size=64, overlap=8)
        assert rep2.skipped is True, "内容未变应跳过（AC-10）"
        _ok("增量索引跳过（AC-10）")
    finally:
        os.unlink(path)


def test_lexical_trigram_cn():
    conn = connect(":memory:")
    migrate(conn, 8)
    enc = FakeEmbedder()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("本地优先知识库测试中文子串命中。\n")
        path = f.name
    try:
        ingest_file(conn, enc, path, chunk_size=64, overlap=8)
        res = retrieve(conn, enc, "知识库", k_fused=5)
        lexical_ids = [cid for cid, _ in res.lexical]
        assert len(lexical_ids) >= 1, "中文子串应被 FTS5 trigram 命中"
        _ok("FTS5 trigram 中文子串命中")
    finally:
        os.unlink(path)


def main() -> int:
    tests = [test_ingest_and_retrieve, test_lexical_trigram_cn]
    failed = 0
    print(f"运行 {len(tests)} 个集成测试...")
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    if failed == 0:
        print(f"\n✅ 全部 {len(tests)} 项通过")
        return 0
    print(f"\n❌ {failed} 项失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
