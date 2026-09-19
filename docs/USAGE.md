# Tekmor — 使用指南（USAGE v1，待确认）

> 作者：晨星 ｜ 适用版本：本地优先 / CPU-only
> 本文件描述终端用户与开发者如何使用 Tekmor 的四件套（ingest / retrieve / cite / answer）。

## 1. 快速开始

```bash
# 1) 安装（干净环境一键复现）
cd tekmor && uv sync --frozen

# 2) 自诊断
uv run tekmor doctor

# 3) 拉取嵌入模型（仅一次）
uv run tekmor models pull embed

# 4) 确保 Ollama 已启动且已拉 LLM
ollama serve &
ollama pull qwen2.5:3b-instruct-q4_K_M

# 5) 导入知识库
uv run tekmor ingest ./docs/ --recursive

# 6) 启动服务
uv run tekmor serve --port 8000

# 7) 打开控制台 console/index.html（file:// 或经 http）
```

## 2. CLI 命令（`cli/main.py`）

| 命令 | 作用 | 示例 |
|---|---|---|
| `tekmor doctor` | 自诊断 + 修复依赖冲突 / 编译失败 / 运行时错误 | `uv run tekmor doctor` |
| `tekmor models pull <embed\|llm>` | 获取并校验模型（sha256） | `uv run tekmor models pull embed` |
| `tekmor ingest <path>` | 解析切片 + 增量 hash 检测 + 写索引 | `uv run tekmor ingest ./kb --recursive` |
| `tekmor serve` | 启动 FastAPI 后端（SSE 流式） | `uv run tekmor serve --port 8000` |
| `tekmor eval` | 跑黄金向量回归 / 命中率 / 拒答率 / 延迟 | `uv run tekmor eval --golden ./golden.jsonl` |

## 3. API 端点（`api/app.py` + `api/routes/`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/ingest` | 上传 / 指定路径导入文档，返回 `IngestReport` |
| POST | `/api/query` | 混合检索 + 证据闸门，返回带 citation 的候选 |
| POST | `/api/answer` | 聚合层：retrieve → (load LLM) → answer → (unload LLM)，SSE 流式 |
| GET | `/api/health` | 内存 / 线程 / 模型状态自检 |
| GET | `/api/features` | 当前 AC 能力清单与开关状态 |

所有响应体走 canonical 序列化（`ensure_ascii=False` + 稳定 key 顺序），与 aetheros 黄金向量字节级对齐。

## 4. 控制台（`console/index.html`）

- **零依赖单文件 HTML**：内联 CSS/JS，无 CDN、无构建。
- **两种打开方式**：
  - 经 HTTP：由 `tekmor serve` 托管，`fetch` 调 `/api/*`。
  - `file://` 离线：AC-12 要求离线也能渲染完整流程（此时无法调后端，仅展示本地自检）。
- **界面继承 aetheros 设计系统**：`--aos-*` token、Tabler 3.46.0（16/20/24px，stroke 恒 2）、五态语义：
  - verified = 青色 trace（Trace Is Cyan）
  - unverified = 琥珀色（Amber Means Unverified）
  - refused = 最暗 inset 底 + strong 环 + 锁形（无 hue 形式化）
  - error = 警示八边形
  - failed = 降级态

## 5. 证据模式（strict / lenient）

| 模式 | 行为 | 何时用 |
|---|---|---|
| **strict（默认）** | claim 无法绑定检索 span → 拦截，标记 evidence-gap；citation 不支持 → citation-unverified | 合规 / 审计场景，零幻觉优先 |
| **lenient** | 允许低置信 claim 通过，但**每条 trace 永久标记 lenient**（AC-14） | 探索性问答，仅显式开启 |

切换：`POST /api/answer` 的 `mode` 字段，或控制台顶部开关（lenient 开启时有醒目永久标识）。

## 6. 典型工作流示例

```
用户：Tekmor 如何处理中文子串检索？
→ retrieve: 向量召回 top-50 + FTS5 trigram 词法召回 top-50
→ fuse: RRF(K=60) 二次融合
→ gate: 每个 claim 锚定到 chunk span，无证据则拦截
→ answer(LLM 载入 → 生成带 citation 的回答 → LLM 驱逐)
→ 控制台渲染：claim 后附可点击 citation（青色=verified）
```

## 7. 离线自检

- 断网后 `uv run tekmor eval --offline`：断言 `getOutbound() === 0`（AC-01）。
- 控制台 `file://` 打开即离线渲染（AC-12）。

## 8. 开发者验证

```bash
uv run pytest -q                 # 单元 + 对抗 fixture（RRF 倒序 reranker 等）
uv run tekmor eval --golden ...  # 黄金向量回归
uv run tekmor doctor             # 门禁全绿
```

---
*本使用指南与 ARCHITECTURE.md §5 接口签名、PRD.md 验收标准严格一致。*
