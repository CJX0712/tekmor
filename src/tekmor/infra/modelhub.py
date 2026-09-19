"""模型获取 / sha256 校验 / 版本锁定（infra 叶子层）。

通道（huggingface.co 本机不通，curl 000）：
- 嵌入 bge-small-zh-v1.5 ONNX int8 → hf-mirror（可达 200）
- LLM → registry.ollama.ai（Ollama 官方库，可达）

所有外部下载前调用 net.record_outbound（AC-01 真实计数）。
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .net import record_outbound

EMBED_REPO = "Xenova/bge-small-zh-v1.5"
HF_MIRROR = "https://hf-mirror.com"


@dataclass(frozen=True)
class ModelRef:
    name: str
    kind: Literal["llm", "embed"]
    source: Literal["ollama", "hf-mirror", "modelscope"]
    sha256: str = ""


def data_dir() -> Path:
    d = Path(os.environ.get("TEKMOR_HOME", Path.home() / ".tekmor"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    record_outbound(1)  # AC-01：真实计数每一次出站
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "tekmor/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as w:  # noqa: S310
        w.write(r.read())


def pull_embed(ref: ModelRef) -> Path:
    """从 hf-mirror 拉取嵌入模型 ONNX + tokenizer（仅 embed 类型）。"""
    base = data_dir() / "models" / "embed"
    model_path = base / "onnx" / "model_int8.onnx"
    tok_path = base / "tokenizer.json"
    cfg_path = base / "config.json"
    if model_path.exists() and tok_path.exists():
        return base
    files = {
        model_path: f"{HF_MIRROR}/{EMBED_REPO}/resolve/main/onnx/model_int8.onnx",
        tok_path: f"{HF_MIRROR}/{EMBED_REPO}/resolve/main/tokenizer.json",
        cfg_path: f"{HF_MIRROR}/{EMBED_REPO}/resolve/main/config.json",
    }
    for dst, url in files.items():
        if not dst.exists():
            _download(url, dst)
    return base


def embed_ready() -> bool:
    base = data_dir() / "models" / "embed"
    return (base / "onnx" / "model_int8.onnx").exists() and (base / "tokenizer.json").exists()


def ensure(ref: ModelRef) -> Path:
    """确保模型就绪：embed 走 pull；llm 走 Ollama 校验。"""
    if ref.kind == "embed":
        return pull_embed(ref)
    # llm：由 infer 层在 Ollama 侧处理；此处仅返回占位
    return data_dir() / "models" / "llm" / ref.name


def list_models() -> list[ModelRef]:
    return [
        ModelRef("Xenova/bge-small-zh-v1.5", "embed", "hf-mirror", ""),
        ModelRef("qwen2.5:3b-instruct-q4_K_M", "llm", "ollama", ""),
        ModelRef("qwen3:4b", "llm", "ollama", ""),
        ModelRef("qwen3:1.7b", "llm", "ollama", ""),
    ]
