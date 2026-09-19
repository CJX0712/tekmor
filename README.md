# Tekmor · 本地优先的证据锚定知识库

> 作者：晨星 ｜ 本地优先 / 端到端可验证 / CPU-only / 零出站
> 古希腊语 τέκμωρ = 确证 / 凭证。与 aetheros 同源品牌家族；aetheros 仅作只读参考源。

## 一句话

在**完全离线**的个人机器上，让 AI 的每句回答都**锚定到原文证据**，且**可审计、可重建、不可篡改**。

## 能力（验收 AC-01..AC-14）

| 维度 | 说明 |
|---|---|
| 离线底线 | 未配置云时 ingest→retrieve→cite→answer 全流程零出站（AC-01） |
| 证据锚定 | 段落级 byte↔utf16 双区间引用，可点击回原文（AC-04/05/06） |
| 混合检索 | 向量 + FTS5 trigram 词法 + RRF 二次融合 + rerank 第三路信号（AC-07/08） |
| 可审计 | append-only 哈希链，180 天留存裁剪不断路（AC-09） |
| 增量 | 内容 hash 未变跳过重嵌（AC-10） |
| 兜底 | 中文无相关 → 拒答而非幻觉（AC-11） |
| 单文件 | `console/index.html` 零依赖，`file://` 离线渲染完整流程（AC-12） |
| 降级 | 端口/模型缺失保持 retryable，线程钳 [2,4]（AC-02/03/13/14） |

## 技术栈（均经实测可获取）

Python 3.13 · uv 0.12.10 · Ollama 0.34.0（钉 `OLLAMA_LLM_LIBRARY=cpu`）· sqlite-vec 0.1.9 ·
FTS5 `trigram` · bge-small-zh-v1.5 ONNX int8（hf-mirror）· FastAPI + uvicorn + sse-starlette ·
onnxruntime 1.30.0 · opentelemetry-sdk。

## 快速开始

```bash
uv sync --frozen            # 安装锁定依赖（无编译器，全预编译 wheel）
uv run tekmor doctor        # 自诊断
uv run tekmor models pull embed
ollama pull qwen2.5:3b-instruct-q4_K_M
uv run tekmor ingest ./docs/
uv run tekmor serve         # 默认 8000，被占用自动回退 8765/8801/9000
# 浏览器打开 console/index.html（或经 http）
```

## 内存建议

当前实测空闲 ~1.04–1.46GB；跑满 3B 档需 ≥3.6GB 空闲。请释放 WSL2 / Docker / Pi Node / Edge 等。
F2/F3/F4 + ingest/retrieve **不依赖 LLM**，可在小内存下完整验证。

## 模块划分（依赖只向下）

`domain`（纯算法）→ `infra`（适配）→ `repositories`（存取）→ `services`（编排）→ `api`/`cli`（装配）→ `console`（单文件 HTML）。

## 文档

- `docs/ARCHITECTURE.md` 系统架构与模块划分
- `docs/PRD.md` 产品需求
- `docs/DEPLOY.md` 部署指南
- `docs/USAGE.md` 使用指南

## 测试

```bash
uv run pytest                 # 含集成（sqlite-vec 缺失时自动降级纯 Python 余弦）
```

> 注：`uv.lock` 与 `requirements.lock` 在目标机器首次 `uv sync` 时生成（本仓库交付 `pyproject.toml` 为版本锁定源）。
