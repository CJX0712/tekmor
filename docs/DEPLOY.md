# Tekmor — 部署指南（DEPLOY v1，待确认）

> 作者：晨星 ｜ 适用版本：本地优先 / CPU-only / Windows + Linux
> 本文件描述如何在干净环境中复现 Tekmor，所有版本号与可用性均经本机实测。

## 1. 环境前置（实测基线）

| 组件 | 版本 / 说明 | 状态 |
|---|---|---|
| OS | Windows 11 家庭中文版（亦支持 Linux x64） | ✅ |
| Python | 3.13.14（cp313） | ✅ 已装 |
| uv | 0.12.10 | ✅ 已装 |
| Ollama | 0.34.0（**关闭自动更新**） | ✅ 已装，需 `ollama serve` |
| SQLite | 3.53.4（bundled，含 FTS5 + 加载 sqlite-vec） | ✅ |
| 编译器 | **无 cl/gcc/cmake/rustc/go** | ⚠️ 故只接受预编译 wheel |

> **硬约束**：本机无编译器，所有依赖**必须是预编译 wheel 或纯 Python**。已证伪：llama-cpp-python / hnswlib / lancedb（无 win wheel）/ 任何源码编译包。

## 2. 内存建议（关键）

实测空闲内存 **1.04–1.46GB**（负载 90%+）。各档峰值：

| 档 | 含常驻峰值 | 需空闲 ≥ |
|---|---|---|
| 救命 1.7B | ≈ 2.0GB | 2.6GB |
| **默认 3B** | ≈ 2.85GB | 3.6GB |
| 大档 4B（已缓存） | ≈ 3.7GB | 4.5GB |
| 用户目标 | — | **≥ 5GB** |

**当前内存不足以跑 LLM 半边**，但 F2/F3/F4/ingest/retrieve 不依赖 LLM，可在 1.46GB 下完整验证。要跑满 3B 档，需释放内存：

| 动作 | 可释放 |
|---|---|
| 停 WSL2（`vmmemWSL` 含 crawl4ai） | 837MB |
| 停 Docker Desktop | 221MB |
| 退出 Pi Node（×2） | 264MB |
| 关 Edge（×4） | ~700MB |
| 收敛 WorkBuddy 额外实例 | ~1.0–1.5GB |
| **合计** | **≈ 3.0–3.5GB → 空闲 ≈ 4.1–5.0GB** |

## 3. 一键复现（依赖锁定）

```bash
# 克隆（地址待用户指定）后
cd tekmor
uv sync --frozen          # 装锁定依赖，零编译
uv run tekmor doctor      # 自诊断 + 修复依赖冲突/编译失败/运行时错误
```

- 锁定文件：`uv.lock`（精确版本）+ `requirements.lock`（发布用）。
- `doctor` 移植自 aetheros 的 harness：offline-guard 拦截任何出站；check-icons / check-policy 移植为 uv 版 CI 门禁。

## 4. 模型获取（huggingface.co 本机不通，curl 000）

| 模型 | 通道 | 命令 / 说明 |
|---|---|---|
| 嵌入 bge-small-zh-v1.5 int8 | hf-mirror 200 | `uv run tekmor models pull embed`（拉 ONNX 22.8MB） |
| LLM 默认 qwen2.5:3b | registry.ollama.ai 可达 | `ollama pull qwen2.5:3b-instruct-q4_K_M` |
| LLM 大档 qwen3:4b | 已缓存 | 直接可用 |
| LLM 救命档 qwen3:1.7b | registry.ollama.ai | `ollama pull qwen3:1.7b` |

> 备选：modelscope.cn 200 可用；若 Ollama 不可用，fallback 为 llama.cpp tag b11042 的 `llama-b11042-bin-win-cpu-x64.zip`（CPU-only）。

## 5. Ollama 配置（CPU-only 钉死）

创建 / 修改 Ollama 环境（避免静默回退探测开销）：

```bash
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_NUM_PARALLEL=1
OLLAMA_KEEP_ALIVE=0          # 答完即驱逐；追问可放宽 30–60s
OLLAMA_NUM_THREADS=4         # 实测 4 线程 32.5 tok/s > 16 线程 8.2 tok/s
OLLAMA_CONTEXT_LENGTH=4096
OLLAMA_KV_CACHE_TYPE=q8_0    # KV 减半
OLLAMA_LLM_LIBRARY=cpu       # 780M 无 ROCm kernel，显式钉死 CPU
```

启动：`ollama serve`（默认 127.0.0.1:11434）。

## 6. 启动服务与控制台

```bash
# 后端（FastAPI + uvicorn）
uv run tekmor serve --host 127.0.0.1 --port 8000
# 端口不可用自动回退：8765 / 8801 / 9000（AC-13）

# 控制台：单文件 HTML（零依赖）
# 方式 A：经 HTTP 访问（推荐，console/index.html 通过 fetch 调 api）
# 方式 B：file:// 直接打开（AC-12，离线渲染完整流程）
```

## 7. Docker（可选隔离）

`Dockerfile` + `compose.yaml` 提供干净隔离环境（不解决本机内存不足问题，仅解决依赖隔离）。

```bash
docker compose up --build
```

## 8. 门禁链（CI / 本地）

```
lint → typecheck → build → test:offline → verify:demo
```

- `test:offline`：断网环境跑，断言 `getOutbound() === 0`（AC-01）。
- `verify:demo`：单文件 HTML 自检 16/16（移植 aetheros demo 引擎）。

## 9. 故障排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 嵌入加载失败 | 无编译器 / wheel 缺失 | 确认 onnxruntime 1.30.0 cp313-win_amd64 wheel 存在 |
| LLM OOM | 内存不足 | 释放内存至阈值，或切救命档 1.7B |
| 中文检索 0 命中 | FTS5 用 unicode61 | 确认 `tokenize='trigram'` |
| 出站计数非 0 | 误连云 | offline-guard 拦截，检查 modelhub 通道 |
| Ollama 静默回退 | 未钉 cpu | 设 `OLLAMA_LLM_LIBRARY=cpu` |

---
*本部署指南与 ARCHITECTURE.md §3/§4 技术栈与内存预算严格一致。*
