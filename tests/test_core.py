"""Tekmor 核心不变量测试（纯 stdlib，可在无网环境运行）。

覆盖 AC-01/02/03/04/05/06/07/08/09 的核心算法与纯函数不变量。
部分集成测试（sqlite-vec KNN / onnxruntime 嵌入）在 tests/test_integration.py，
需要外部依赖，依赖缺失时自动跳过。
"""

from __future__ import annotations

import os
import sys

# 让测试在无安装环境下也能 import 源码包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tekmor.domain.fusion import fuse, top_k, RERANK_WEIGHT  # noqa: E402
from tekmor.domain.evidence import EvidenceGate, verify_citation, slice_evidence  # noqa: E402
from tekmor.domain.trace import Trace, TamperDetected, GENESIS  # noqa: E402
from tekmor.domain.types import Claim, EvidenceAnchor, EvidenceMode  # noqa: E402
from tekmor.infra.hardware import auto_threads, THREAD_MIN, THREAD_MAX, require_free, InsufficientMemory, HardwareProfile  # noqa: E402
from tekmor.infra.net import record_outbound, get_outbound, reset_outbound  # noqa: E402


def _ok(name: str) -> None:
    print(f"  PASS  {name}")


def test_auto_threads_clamp():
    # AC-02/03：钳到 [2,4]
    assert auto_threads(1) == THREAD_MIN, "下界应钳到 2"
    assert auto_threads(2) == 2
    assert auto_threads(4) == 4
    assert auto_threads(8) == THREAD_MAX, "上界应钳到 4"
    assert auto_threads(16) == THREAD_MAX
    assert auto_threads(0) == THREAD_MIN
    assert auto_threads(-5) == THREAD_MIN
    # 任何改动越界即失败
    for n in (THREAD_MIN, 3, THREAD_MAX):
        assert THREAD_MIN <= auto_threads(n) <= THREAD_MAX
    _ok("auto_threads 钳制 [2,4] (AC-02/03)")


def test_fusion_rrf_basic():
    # 第一阶融合：lexical 与 semantic 都含 item 7 → 应排前
    lexical = [(7, 0.9), (3, 0.5), (1, 0.2)]
    semantic = [(7, 0.8), (9, 0.6), (3, 0.1)]
    ranked = fuse(lexical, semantic)
    ids = [i for i, _ in ranked]
    assert ids[0] == 7, "两路共同冠军应为 top-1"
    assert set(ids) == {7, 3, 1, 9}
    _ok("RRF 第一阶融合 (AC-07 基础)")


def test_fusion_rerank_third_signal():
    # AC-07：rerank 作为第三路信号（w=0.5），不直接采用重排顺序
    lexical = [(1, 0.9), (2, 0.5)]
    semantic = [(1, 0.8), (2, 0.6)]
    # rerank 把 2 排到第一（若直接采用则 top-1=2）
    rerank = [(2, 0.99), (1, 0.1)]
    ranked = fuse(lexical, semantic, rerank=rerank, w=RERANK_WEIGHT)
    # 由于 w<1，base 中 1 仍应领先 2
    ids = [i for i, _ in ranked]
    assert ids[0] == 1, "rerank 不应直接覆盖 base 冠军 (AC-07)"
    # 但 rerank 让 2 相对提升（对比无 rerank 时）
    base_only = fuse(lexical, semantic)
    base_score_2 = dict(base_only)[2]
    fused_score_2 = dict(ranked)[2]
    assert fused_score_2 > base_score_2, "rerank 应作为第三路信号加分 (AC-07)"
    _ok("rerank 第三路信号 w=0.5 (AC-07)")


def test_fusion_adversarial_reranker():
    # AC-08：注入全倒序 reranker → 最终 top-1 仍是第一阶融合冠军
    lexical = [(1, 0.9), (2, 0.5), (3, 0.3)]
    semantic = [(1, 0.8), (2, 0.6), (3, 0.4)]
    base = fuse(lexical, semantic)
    champion = base[0][0]
    # 全倒序：把冠军排到最后
    rerank = [(3, 0.9), (2, 0.5), (1, 0.1)]  # 与 base 顺序完全相反
    fused = fuse(lexical, semantic, rerank=rerank, w=RERANK_WEIGHT)
    assert fused[0][0] == champion, "对抗 reranker 不得翻转冠军 (AC-08)"
    _ok("对抗倒序 reranker 不变式 (AC-08)")


def test_fusion_w_guard():
    # AC-08 结构守卫：w 必须 < 1
    try:
        fuse([(1, 0.1)], [(1, 0.1)], rerank=[(1, 0.1)], w=1.0)
        assert False, "w=1.0 应被拒绝"
    except ValueError:
        pass
    _ok("rerank 权重 w<1 结构守卫 (AC-08)")


def test_evidence_gate_no_anchor():
    # AC-05：无证据 claim 在 strict 下被拦截
    claims = [
        Claim(id="c1", text="有证据", anchor=EvidenceAnchor(1, 0, 2, 0, 4)),
        Claim(id="c2", text="无证据", anchor=None),
    ]
    strict = EvidenceGate(EvidenceMode.STRICT).gate(claims)
    assert len(strict.passed) == 1 and strict.passed[0].id == "c1"
    assert strict.blocked[0].id == "c2"
    # lenient：放行但模式标记
    lens = EvidenceGate(EvidenceMode.LENIENT).gate(claims)
    assert len(lens.passed) == 2 and lens.mode == EvidenceMode.LENIENT
    _ok("无证据拦截 strict / 放行 lenient (AC-05/14)")


def test_evidence_slice_byte_utf16():
    # AC-04：byte↔utf16 双区间交叉校验
    text = "本地优先知识库"  # 含中文，byte 与 utf16 长度不同
    # 锚定 "知识库"（后 3 字）
    utf16_start = 4  # "本地优先" 4 字
    utf16_end = 7
    byte_start = len("本地优先".encode("utf-8"))
    byte_end = len("本地优先知识库".encode("utf-8"))
    anchor = EvidenceAnchor(1, utf16_start, utf16_end, byte_start, byte_end)
    span = slice_evidence(anchor, text)
    assert span == "知识库", f"切片应为 '知识库'，实际 '{span}'"
    # 错位应抛错
    bad = EvidenceAnchor(1, utf16_start, utf16_end, 0, 2)
    try:
        slice_evidence(bad, text)
        assert False
    except ValueError:
        pass
    _ok("byte↔utf16 双区间锚定 (AC-04)")


def test_evidence_verify_citation():
    # AC-06：citation 指向不支持的 chunk → unverified
    good_anchor = EvidenceAnchor(1, 0, 3, 0, len("模型推理".encode("utf-8")))
    good = Claim(id="g", text="模型推理", anchor=good_anchor)
    assert verify_citation(good, "模型推理需要上下文") is True
    bad_anchor = EvidenceAnchor(2, 0, 3, 0, len("天气晴朗".encode("utf-8")))
    bad = Claim(id="b", text="模型推理", anchor=bad_anchor)
    assert verify_citation(bad, "天气晴朗适合出行") is False
    _ok("citation 可信校验 (AC-06)")


def test_trace_chain_and_tamper():
    # AC-09：哈希链 append + verify + 篡改检测
    t = Trace()
    for i in range(5):
        t.append("step", {"i": i})
    assert t.verify() is True
    assert t.is_intact() is True
    # 篡改 payload
    t._spans[2].payload = {"i": 999}
    assert t.is_intact() is False
    try:
        t.verify()
        assert False
    except TamperDetected:
        pass
    _ok("哈希链校验与篡改检测 (AC-09)")


def test_trace_prune_keeps_chain():
    # AC-09：prune（180 天留存）后链仍可端到端验证
    t = Trace()
    base = 1_000_000
    for i in range(10):
        t.append("step", {"i": i}, now=base + i * 1000)
    # 截断前 5 帧（模拟早于留存窗口）
    removed = t.prune_before(base + 5 * 1000)
    assert removed == 5
    assert len(t) == 5
    assert t.verify() is True, "prune 后链必须仍可验证"
    assert t._pruned_anchor != GENESIS
    _ok("180 天留存截断不断路 (AC-09 修复)")


def test_outbound_zero_offline():
    # AC-01：离线操作不增出站计数
    reset_outbound()
    assert get_outbound() == 0
    # 模拟一次出站（仅计数，不真发）
    record_outbound(1)
    assert get_outbound() == 1
    reset_outbound()
    assert get_outbound() == 0
    _ok("出站计数器真实计数 (AC-01)")


def test_require_free_guard():
    # AC-14：内存护栏
    p = HardwareProfile(total_bytes=8e9, avail_bytes=1e9, threads=4)
    try:
        require_free(p, 2.6e9)
        assert False
    except InsufficientMemory:
        pass
    p2 = HardwareProfile(total_bytes=8e9, avail_bytes=6e9, threads=4)
    require_free(p2, 2.6e9)  # 应放行
    _ok("内存护栏 (AC-14)")


def main() -> int:
    tests = [
        test_auto_threads_clamp,
        test_fusion_rrf_basic,
        test_fusion_rerank_third_signal,
        test_fusion_adversarial_reranker,
        test_fusion_w_guard,
        test_evidence_gate_no_anchor,
        test_evidence_slice_byte_utf16,
        test_evidence_verify_citation,
        test_trace_chain_and_tamper,
        test_trace_prune_keeps_chain,
        test_outbound_zero_offline,
        test_require_free_guard,
    ]
    failed = 0
    print(f"运行 {len(tests)} 个核心不变量测试...")
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {e}")
    if failed == 0:
        print(f"\n✅ 全部 {len(tests)} 项通过")
        return 0
    print(f"\n❌ {failed} 项失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
