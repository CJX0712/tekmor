from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["features"])

# AC 能力清单（前端据此渲染开关与状态）
FEATURES = [
    {"ac": "AC-01", "name": "零出站离线底线", "verifiable_offline": True},
    {"ac": "AC-02", "name": "CPU 线程钳 [2,4]", "verifiable_offline": True},
    {"ac": "AC-03", "name": "线程防回退守卫", "verifiable_offline": True},
    {"ac": "AC-04", "name": "段落级证据锚定", "verifiable_offline": True},
    {"ac": "AC-05", "name": "无证据不输出", "verifiable_offline": True},
    {"ac": "AC-06", "name": "引用可信校验", "verifiable_offline": True},
    {"ac": "AC-07", "name": "rerank 第三路信号", "verifiable_offline": True},
    {"ac": "AC-08", "name": "对抗 reranker 不变", "verifiable_offline": True},
    {"ac": "AC-09", "name": "哈希链可重建", "verifiable_offline": True},
    {"ac": "AC-10", "name": "增量索引", "verifiable_offline": True},
    {"ac": "AC-11", "name": "中文兜底拒答", "verifiable_offline": False},
    {"ac": "AC-12", "name": "单文件控制台", "verifiable_offline": True},
    {"ac": "AC-13", "name": "端口/模型降级", "verifiable_offline": False},
    {"ac": "AC-14", "name": "证据模式可见", "verifiable_offline": True},
]


@router.get("/features")
def features() -> dict:
    return {"features": FEATURES, "evidence_modes": ["strict", "lenient"]}
