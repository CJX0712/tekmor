from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...services.retrieve import retrieve

router = APIRouter(prefix="/api", tags=["query"])


class QueryRequest(BaseModel):
    query: str
    k_fused: int = 8


@router.post("/query")
def query(req: QueryRequest, request: Request) -> dict:
    core = request.app.state.core
    conn = core.conn()
    enc = core.encoder()
    res = retrieve(conn, enc, req.query, k_fused=req.k_fused)
    return {
        "fused": [{"chunk_id": c, "score": s} for c, s in res.fused],
        "chunks": {
            str(c): {"text": ch.text, "doc_id": ch.doc_id}
            for c, ch in res.chunks.items()
        },
    }
