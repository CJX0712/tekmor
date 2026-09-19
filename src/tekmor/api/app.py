"""FastAPI 应用工厂（api 只装配 <100 行逻辑）。

路由处理器拆分在 routes/；本文件只负责创建 app、挂载路由、注入共享状态。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..infra.hardware import detect
from ..infra.net import get_outbound
from .routes import answer, features, health, ingest, query


class AppState:
    def __init__(self, db_path: str, embed_threads: int, llm_model: str) -> None:
        self.db_path = db_path
        self.embed_threads = embed_threads
        self.llm_model = llm_model
        self._encoder = None
        self._conn = None

    def conn(self):
        from ..infra.db import connect, migrate

        if self._conn is None:
            self._conn = connect(self.db_path)
            migrate(self._conn, 512)
        return self._conn

    def encoder(self):
        if self._encoder is None:
            from ..infra.embed import load_local_onnx
            from ..infra.modelhub import ensure, ModelRef

            ref_path = ensure(ModelRef("Xenova/bge-small-zh-v1.5", "embed", "hf-mirror"))
            self._encoder = load_local_onnx(ref_path, self.embed_threads)
        return self._encoder


def create_app(db_path: str = "tekmor.db", embed_threads: int = 4, llm_model: str = "qwen2.5:3b-instruct-q4_K_M") -> FastAPI:
    app = FastAPI(title="Tekmor", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    state = AppState(db_path, embed_threads, llm_model)
    app.state.core = state

    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(answer.router)
    app.include_router(health.router)
    app.include_router(features.router)

    @app.get("/api/outbound")
    def outbound() -> dict[str, Any]:
        # AC-01：真实出站计数可见化
        return {"outbound": get_outbound(), "threads": detect().threads}

    return app
