from __future__ import annotations

from fastapi import APIRouter, Request

from ...infra.hardware import detect

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    core = request.app.state.core
    prof = detect()
    # 模型就绪探测（不强制，避免无 Ollama 时崩溃）
    llm_ready = False
    try:
        from ...infra.infer import connect_ollama, resolve_model

        r = resolve_model(core.llm_model)
        llm_ready = r.ok
    except Exception:
        llm_ready = False
    return {
        "status": "ok",
        "threads": prof.threads,
        "avail_bytes": prof.avail_bytes,
        "total_bytes": prof.total_bytes,
        "llm_model": core.llm_model,
        "llm_ready": llm_ready,
    }
