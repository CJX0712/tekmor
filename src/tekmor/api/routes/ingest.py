from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.ingest import ingest_file

router = APIRouter(prefix="/api", tags=["ingest"])


class IngestRequest(BaseModel):
    path: str
    chunk_size: int = 512
    overlap: int = 64


@router.post("/ingest")
def ingest(req: IngestRequest, request: Request) -> dict:
    core = request.app.state.core
    try:
        conn = core.conn()
        enc = core.encoder()
        report = ingest_file(conn, enc, req.path, chunk_size=req.chunk_size, overlap=req.overlap)
        return {
            "doc_id": report.doc_id,
            "chunks": report.chunks,
            "new_chunks": report.new_chunks,
            "skipped": report.skipped,
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
