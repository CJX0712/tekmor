from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ...domain.types import EvidenceMode
from ...services.agent import answer as agent_answer

router = APIRouter(prefix="/api", tags=["answer"])


class AnswerRequest(BaseModel):
    query: str
    mode: str = "strict"  # strict | lenient


@router.post("/answer")
async def answer(req: AnswerRequest, request: Request):
    core = request.app.state.core
    mode = EvidenceMode(req.mode) if req.mode in ("strict", "lenient") else EvidenceMode.STRICT

    async def event_gen():
        try:
            conn = core.conn()
            enc = core.encoder()
            # LLM 懒连接（可驱逐）
            from ...infra.infer import connect_ollama, set_model

            set_model(core.llm_model)
            llm = connect_ollama()

            # 检索阶段（无 LLM 依赖）立即回报，前端可先渲染证据
            from ...services.retrieve import retrieve

            res = retrieve(conn, enc, req.query, k_fused=8)
            yield {
                "event": "evidence",
                "data": json.dumps({
                    "fused": [{"chunk_id": c, "score": s} for c, s in res.fused],
                    "chunks": {str(c): ch.text for c, ch in res.chunks.items()},
                }, ensure_ascii=False),
            }

            ans = agent_answer(conn, enc, llm, req.query, mode=mode)
            # 流式逐字（若 LLM 支持）；否则整体发送
            if ans.refused:
                yield {"event": "token", "data": ans.text}
            else:
                # 简单逐句推送
                for sent in ans.text.split("\n"):
                    if sent.strip():
                        yield {"event": "token", "data": sent + "\n"}
            yield {
                "event": "done",
                "data": json.dumps({
                    "citations": [a.__dict__ for a in ans.citations],
                    "mode": ans.mode,
                    "refused": ans.refused,
                }, ensure_ascii=False),
            }
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": str(e)}

    return EventSourceResponse(event_gen())
