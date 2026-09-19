"""LLM 客户端（infra 叶子层，可驱逐）。Ollama 后端，标准库 urllib/http.client。

关键生命周期（ARCHITECTURE §4）：
- keep_alive=0：答完即驱逐，避免常驻吃内存。
- num_thread=4：实测 4 线程 32.5 tok/s > 16 线程 8.2 tok/s。
- num_ctx=4096 + KV q8_0：KV 减半。
所有请求前 record_outbound（AC-01 真实计数）。
"""

from __future__ import annotations

import http.client
import json
import os
import urllib.request
from typing import Iterator, Protocol

from .net import record_outbound


class ModelResolution:
    """模型解析结果（AC-14：缺失保持 retryable，非硬失败）。"""

    def __init__(self, ok: bool, path: str = "", retryable: bool = False, reason: str = "") -> None:
        self.ok = ok
        self.path = path
        self.retryable = retryable
        self.reason = reason


class LlmClient(Protocol):
    def chat(
        self,
        messages: "list[dict]",
        *,
        stream: bool,
        keep_alive: str,
        num_ctx: int,
        num_thread: int,
    ) -> "Iterator[str] | str": ...

    def unload(self) -> None: ...


def _http_post_json(host: str, port: int, path: str, payload: dict) -> dict:
    record_outbound(1)
    conn = http.client.HTTPConnection(host, port, timeout=600)
    body = json.dumps(payload).encode("utf-8")
    conn.request("POST", path, body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    if resp.status != 200:
        raise RuntimeError(f"Ollama 返回 {resp.status}: {data[:200]}")
    return json.loads(data)


def _stream_post(host: str, port: int, path: str, payload: dict) -> Iterator[str]:
    record_outbound(1)
    import urllib.request

    req = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310
        for line in r:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("done"):
                break
            if "response" in obj:
                yield obj["response"]


class _OllamaClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 11434) -> None:
        self.host = host
        self.port = port

    def available(self) -> bool:
        try:
            _http_post_json(self.host, self.port, "/api/show", {"model": ""})
            return True
        except Exception:
            return False

    def chat(
        self,
        messages: "list[dict]",
        *,
        stream: bool,
        keep_alive: str = "0",
        num_ctx: int = 4096,
        num_thread: int = 4,
    ) -> "Iterator[str] | str":
        payload = {
            "model": _current_model(),
            "messages": messages,
            "stream": stream,
            "keep_alive": keep_alive,
            "options": {"num_ctx": num_ctx, "num_thread": num_thread},
        }
        if stream:
            return _stream_post(self.host, self.port, "/api/chat", payload)
        data = _http_post_json(self.host, self.port, "/api/chat", payload)
        return data.get("message", {}).get("content", "")

    def unload(self) -> None:
        try:
            _http_post_json(
                self.host, self.port, "/api/generate",
                {"model": _current_model(), "prompt": "", "keep_alive": 0},
            )
        except Exception:
            pass


_MODEL_ENV = "TEKMOR_LLM"


def _current_model() -> str:
    return os.environ.get(_MODEL_ENV, "qwen2.5:3b-instruct-q4_K_M")


def set_model(name: str) -> None:
    import os

    os.environ[_MODEL_ENV] = name


def connect_ollama(base_url: str = "http://127.0.0.1:11434") -> LlmClient:
    # base_url 形如 http://127.0.0.1:11434
    from urllib.parse import urlparse

    p = urlparse(base_url)
    return _OllamaClient(p.hostname or "127.0.0.1", p.port or 11434)


def resolve_model(name: str) -> ModelResolution:
    """解析 Ollama 模型是否存在（AC-14：缺失 retryable）。"""
    import os

    # 命中缓存路径（Ollama 默认 blobs）则视为就绪
    ollama_home = os.environ.get("OLLAMA_MODELS", os.path.expanduser("~/.ollama"))
    blob_dir = os.path.join(ollama_home, "models", "manifests", "registry.ollama.ai", "library")
    # 仅做轻量探测：检查 manifests 目录是否存在该模型
    candidate = os.path.join(blob_dir, name.replace(":", "/"))
    if os.path.exists(candidate):
        return ModelResolution(ok=True, path=candidate)
    # 否则尝试通过 API 查询
    try:
        client = connect_ollama()
        data = _http_post_json(client.host, client.port, "/api/tags", {})
        tags = {m["name"] for m in data.get("models", [])}
        if name in tags:
            return ModelResolution(ok=True, path=name)
        return ModelResolution(ok=False, retryable=True, reason=f"模型 {name} 未拉取，请 `ollama pull {name}`")
    except Exception as e:  # noqa: BLE001
        return ModelResolution(ok=False, retryable=True, reason=str(e))
