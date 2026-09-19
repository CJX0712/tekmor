"""进程内 ONNX 嵌入器（infra 叶子层，常驻）。

bge-small-zh-v1.5：维度 512，mean-pooling + L2 归一化（与 Xenova ONNX 约定一致）。
常驻进程内（不驱逐），与可驱逐的 LLM 永不同时驻留（ARCHITECTURE §4 生命周期）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def encode(self, texts: "list[str]", *, batch: int = 8) -> "np.ndarray":
        """返回形状 (len(texts), dim) 的 float32 矩阵（已 L2 归一化）。"""
        ...


def _mean_pool(last_hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    mask = mask[:, :, None].astype(np.float32)
    summed = (last_hidden * mask).sum(axis=1)
    denom = mask.sum(axis=1) + 1e-9
    return summed / denom


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-9)


class _OnnxEmbedder:
    def __init__(self, model_path: Path, tokenizer_path: Path, threads: int, dim: int = 512) -> None:
        import onnxruntime as ort  # 延迟导入（仅在用户机器装好 wheel 后）
        from tokenizers import Tokenizer

        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = threads
        self.sess = ort.InferenceSession(
            str(model_path), so, providers=["CPUExecutionProvider"]
        )
        self.tok = Tokenizer.from_file(str(tokenizer_path))
        self.dim = dim

    def encode(self, texts: "list[str]", *, batch: int = 8) -> "np.ndarray":
        if isinstance(texts, str):
            texts = [texts]
        out: list[np.ndarray] = []
        for i in range(0, len(texts), batch):
            grp = texts[i : i + batch]
            encs = [self.tok.encode(t, add_special_tokens=True) for t in grp]
            max_len = max(len(e.ids) for e in encs)
            ids = np.zeros((len(grp), max_len), dtype=np.int64)
            mask = np.zeros((len(grp), max_len), dtype=np.int64)
            for r, e in enumerate(encs):
                n = len(e.ids)
                ids[r, :n] = e.ids
                mask[r, :n] = 1
            res = self.sess.run(
                None,
                {
                    "input_ids": ids,
                    "attention_mask": mask,
                    "token_type_ids": np.zeros_like(ids),
                },
            )
            last_hidden = res[0].astype(np.float32)
            pooled = _mean_pool(last_hidden, mask)
            out.append(_l2_normalize(pooled))
        return np.vstack(out).astype(np.float32)


def load_local_onnx(ref_path: Path, threads: int) -> Embedder:
    """从 modelhub 落盘的目录加载嵌入器。ref_path 含 onnx/ 与 tokenizer.json。"""
    model_path = ref_path / "onnx" / "model_int8.onnx"
    tokenizer_path = ref_path / "tokenizer.json"
    if not model_path.exists() or not tokenizer_path.exists():
        raise FileNotFoundError(
            f"嵌入模型缺失：{model_path} / {tokenizer_path}。请先 `tekmor models pull embed`"
        )
    return _OnnxEmbedder(model_path, tokenizer_path, threads)
