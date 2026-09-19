# Tekmor — 系统架构与模块划分（草案 v1，待确认）

> 作者：晨星 ｜ 状态：Phase 1 调研完成，待用户确认后进入 Phase 2 实现
> 本文件是「整体方案与模块划分」的权威载体；PRD.md 是产品侧输入，DEPLOY.md / USAGE.md 是交付文档。

## 0. 决策基线（Phase 0 + 用户确认，已锁定）

| 项 | 结论 | 来源 |
|---|---|---|
| 定位 | 本地可验证 RAG 知识库 + Agent 平台；MVP 先打通 RAG 链路，Agent 层（F7）延后到 P2 | 用户确认 |
| 与 aetheros 关系 | 新建独立项目 `tekmor`，**窄移植** aetheros 内核（fusion / evidence / trace 三个算法模块到 Python）；aetheros 作为只读参考源 | 用户确认 + 架构裁决 |
| 主语言 | **Python 3.13 为主** + 单文件 HTML 控制台（零依赖、`file://` 可开） | 用户确认 |
| 模型策略 | 双档可切换，**默认 3B**；救命档 1.7B，大档 4B | 用户确认 |
| 署名 | 全部代码与文档署名「晨星」 | 用户确认 |
| 命名 | **tekmor**（古希腊语 τέκμωρ = 确证/凭证；PyPI 与 npm 裸名双通道均未占用，且与 aetheros 同源可做品牌家族） | PM 实测 |
| 设计继承 | 继承 aetheros 已锁死的设计系统（`--aos-*` token、Tabler 3.46.0、五态语义、Trace Is Cyan / Amber Means Unverified 硬规则） | 设计师实测 |

## 1. 复用裁决：窄移植（b），不是边车（a）

aetheros 是 TypeScript / Node（pnpm monorepo），新项目主语言是 Python。三者对比：

| 维度 | (a) 边车 Node 服务 | (b) 窄移植 Python | (c) 改主语言 TS |
|---|---|---|---|
| 常驻额外内存 | +80–150MB（Node/V8 + 原生模块 + HTTP 服务） | **0** | 约 +60–120MB（onnxruntime-node） |
| 是否改 aetheros | 要（加 server 入口）→ 违反只读 | 不要 | — |
| 能否满足「修复版 pruneBefore」 | 否（继承缺陷且不能改源） | **是** | 是 |
| 依赖链 | pnpm（本机未装）+ Node + TS build + npm（registry 指向 ohpm 默认 404） | 无（uv 已装） | pnpm 未装 + better-sqlite3 原生扩展未验证 |
| 跨进程风险 | canonical 编码要走 wire format（跨语言高危区） | 进程内，黄金向量锁死 | 单一语言 |
| 工量 | 新建服务 + IPC + 双进程编排 | ~400–500 行纯算法 | 丢弃本轮全部 Python 实测 |

**结论：窄移植。** 移植面仅 ~500 行纯算法（fusion / evidence / trace / types / net / infer / runtime 的算法核心），换来零额外运行时与单工具链；与已锁主语言一致；且 aetheros 内核的缺陷修复已本轮落到 TS 侧（`a1fef02`），Tekmor 直接移植修复版，无分叉。

**复用三分法**：
- **直接复用（零成本，语言无关）**：aetheros 的 `docs/SPEC.md`、`docs/architecture/ARCHITECTURE.md`、`docs/api/openapi.yaml`、`ADR-001~018`、`docs/design/design-tokens.{json,css}`、`docs/design/tabler-icon-manifest.md`、门禁**规则**（移植为 uv 版）。
- **移植（~1–2 天）**：fusion / evidence / trace / types / net / infer / runtime 的算法核心到 Python。
- **丢弃**：aetheros 的 `packages/ui`（TS 组件）、`packages/cli`（TS CLI）、`packages/demo`（TS 单文件）— Tekmor 用 FastAPI + 单文件 HTML 重建。

## 2. 模块划分与依赖方向

依赖**只向下**，禁止反向引用。每模块独立可测，再串联成完整链路。

```
tekmor/
├── domain/            # 叶子层，零依赖，纯算法 + 类型
│   ├── types.py       # Chunk / Claim / EvidenceAnchor / EvidenceMode / RunInput / RunResult
│   ├── fusion.py      # RRF 二次融合（AC-06/07/08 不变量载体）
│   ├── evidence.py    # EvidenceGate + sliceEvidence（byte↔utf16 双区间锚定）
│   └── trace.py       # 哈希链 append-only + verify() + 180 天留存（修复版）
├── infra/             # 叶子层，外部依赖适配
│   ├── hardware.py    # 内存探测 + 线程钳制 + require_free 护栏
│   ├── db.py          # SQLite 连接 / FTS5 + sqlite-vec 加载 / 迁移
│   ├── modelhub.py    # 模型获取 / sha256 校验 / 版本锁定（魔搭 / hf-mirror / Ollama）
│   ├── infer.py       # LLM 客户端（Ollama，可驱逐：keep_alive / num_thread）
│   └── embed.py       # 嵌入器（进程内 ONNX，常驻）
├── repositories/      # 只存取，不含业务判断
│   ├── index_repo.py  # 向量索引（sqlite-vec）+ 词法索引（FTS5 trigram）的 upsert/knn/search
│   └── trace_repo.py  # 哈希链的持久化封装
├── services/          # 业务编排
│   ├── ingest.py      # 解析切片 + 增量 hash 检测
│   ├── retrieve.py    # 混合检索 + RRF + 重排信号槽（确定性打分器，无模型）
│   ├── agent.py       # 唯一聚合层：retrieve → (load LLM) → answer → (unload LLM)
│   └── eval.py        # 黄金向量回归 / 命中率 / 拒答率 / 延迟
├── api/               # 只装配，<100 行 app 工厂
│   ├── app.py         # create_app()
│   └── routes/        # query / ingest / health / features（SSE 流式）
├── cli/               # 可脱离 server 单独跑
│   └── main.py
└── console/           # 单文件 HTML，仅经 HTTP 访问 api
    └── index.html
```

**依赖铁律（收紧 SPEC §4 的模糊处）**：
- `api → services`；`services → repositories, infra`；`repositories → infra`；`infra` 不依赖上层；`domain` 被任意层依赖但自身零依赖。
- `api` 只准碰 services（禁 `api → repositories / infra`）。
- `repositories` 只做存取，禁 `if mode == 'strict'` 等业务判断进 repo。
- `agent` 禁 import FastAPI / 任何 web 框架。
- **新增 `db` 模块**：否则 `index` 与 `trace` 各自 init DB 会跨模块直连数据层，违反分层。

> 注：`embed` 从 `infer` / `modelhub` 拆出——两者生命周期相反（嵌入器常驻进程内 ONNX，LLM 可驱逐外部进程），合并会强制同一策略。`fusion` 从 `retrieve` 拆出——它是纯算法 + 对抗性不变量的载体，混进 retrieve 会把不变量埋掉。

## 3. 技术栈锁定表（均已实测可获取 / 有预编译产物）

```
运行时     Python 3.13.14 | uv 0.12.10（已装）| Ollama 0.34.0（已装，关自动更新）| SQLite(bundled) 3.53.4
向量检索   sqlite-vec 0.1.9（win_amd64 wheel，已端到端 KNN 实测 PASS）
词法检索   SQLite FTS5 tokenize='trigram'（中文子串命中实测；unicode61 中文 0 命中）
嵌入       bge-small-zh-v1.5 = Xenova/bge-small-zh-v1.5 onnx/model_int8.onnx (22.8MB, hf-mirror)，进程内 ONNX
LLM       默认 qwen2.5:3b-instruct-q4_K_M（需 pull）| 大档 qwen3:4b（已缓存）| 救命档 qwen3:1.7b
API        FastAPI 0.141.1 + uvicorn 0.53.0 + sse-starlette 3.4.11（均 py3-none-any）
观测       opentelemetry-sdk 1.44.0（惰性初始化，仅配置 OTLP 时 emit GenAI semconv）
解析       pypdf 6.19.0 或 pymupdf 1.28.2（MVP 仅纯文本/Markdown/txt，docx 可选）
onnx       onnxruntime 1.30.0（cp313-win_amd64）；tokenizers 0.23.2；numpy 2.5.x
图标       @tabler/icons 3.46.0（沿用 aetheros 同一套，尺寸 16/20/24，stroke 恒 2）
字体       Geist + Commit Mono（OFL 1.1，走 fallback 栈，不依赖 CDN）
fallback   llama.cpp tag b11042 的 llama-b11042-bin-win-cpu-x64.zip（仅当 Ollama 不可用时）
```

**已证伪、Spec 中不得出现**：`llama-cpp-python`（sdist-only，无编译器）、`hnswlib`（sdist-only）、`lancedb`（无 win wheel 的版本）、`jieba`（不必要）、任何依赖源码编译的包、任何 780M（gfx1103）加速方案（`OLLAMA_LLM_LIBRARY=cpu` 显式钉死，避免静默回退探测开销）。

**模型获取通道**（huggingface.co 在本机完全不通，curl 000）：`registry.ollama.ai` 可达、hf-mirror.com 200、modelscope.cn 200。嵌入走 hf-mirror 拉 ONNX；LLM 走 `ollama pull`（官方库）。

## 4. 内存预算与生命周期（对照实测 1.04–1.46GB 空闲）

**实测基线**：total 15.26GB，avail **1.04GB → 1.46GB**（负载 90–93%）。

**常驻（Tekmor Python 进程，AI 估算 + 实测体积）**：

| 组件 | 常驻 |
|---|---|
| python 3.13 + 解释器 | 30MB |
| FastAPI / uvicorn / pydantic / starlette | 60MB |
| numpy | 30MB |
| onnxruntime 基线 | 100MB |
| tokenizers + bge-small-zh int8 权重/arena | 80MB |
| sqlite-vec 索引（50k×512 f32） | ~120MB |
| FTS5 trigram 索引（50k chunk） | ~80MB |
| 缓冲 / GC 余量 | 80MB |
| **常驻小计** | **≈ 0.55–0.70GB** |

**峰值（常驻 + 一次性 LLM）**：

| 档 | 权重 | KV@4096(q8_0) | 缓冲 | LLM 小计 | 含常驻峰值 |
|---|---|---|---|---|---|
| 救命 1.7B | ~1.1GB | ~40MB | ~250MB | ~1.4GB | **≈ 2.0GB** |
| **默认 3B** | ~1.9GB | ~72MB | ~300MB | ~2.25GB | **≈ 2.85GB** |
| 大档 4B（已缓存） | 2.5GB | ~288MB | ~300MB | ~3.1GB | **≈ 3.7GB** |

**阈值**：3B 档需空闲 ≥ 3.6GB（含 0.75GB 余量）；4B 档 ≥ 4.5GB；**用户目标 ≥ 5GB**（Windows 自留 ~1GB）。

**当前 1.46GB 空闲 → 连救命档（2.0GB）都装不下 → 端到端「实际运行」在当前内存下不可行。** 但 **F2/RRF、F3/trace、F4/证据闸门 + ingest/retrieve 全部不需要 LLM**，只吃常驻 0.55–0.70GB——**在 1.46GB 下这四项可完整端到端验证**。只有 F1 的 LLM 半边被内存卡住，按 AC-14 降级为「已装配但显式提示内存不足、不出站、不 OOM」。**4 个 P0 里有 3 个不依赖用户清理即可交付验收。**

**必须释放内存（不止停 Pi Node）**：

| 动作 | 实测可释放 |
|---|---|
| 停 WSL2（`vmmemWSL` 837MB）→ crawl4ai 就在这层 | 837MB |
| 停 Docker Desktop（`com.docker.backend` 221MB） | 221MB |
| 退出 Pi Node（`Pi Network.exe` ×2 = 264MB） | 264MB |
| 关 Edge（`msedge` ×4） | ~700MB |
| 收敛 WorkBuddy 额外实例 | ~1.0–1.5GB |
| **合计** | **≈ 3.0–3.5GB → 空闲 ≈ 4.1–5.0GB** |

**生命周期管理（必须落成代码，非文档口号）**：
1. `OLLAMA_MAX_LOADED_MODELS=1`、`OLLAMA_NUM_PARALLEL=1`（并行会成倍占内存）。
2. `OLLAMA_KEEP_ALIVE=0`（回答后立即驱逐 LLM；追问体验可给 30–60s 宽限，默认 0）。
3. `OLLAMA_NUM_THREADS=4` + 请求级 `options.num_thread=4`（实测 4 线程 32.5 tok/s vs 16 线程 8.2 tok/s）。
4. `OLLAMA_CONTEXT_LENGTH=4096` + `OLLAMA_KV_CACHE_TYPE=q8_0`（KV 减半）。
5. `OLLAMA_LLM_LIBRARY=cpu`：显式钉死 CPU（780M gfx1103 缺 ROCm kernel、Vulkan ICD 未注册，静默回退是已知事实）。
6. **严格串行**：embed → retrieve → (load LLM) → answer → (unload LLM)；嵌入器常驻、LLM 可驱逐，两者永不同时驻留。
7. 硬护栏：载入 LLM 前调 `hardware.require_free(2.6GB)`，不足返回友好错误（AC-14 韧性），不得 OOM 崩进程。

## 5. 接口签名（Python 类型注解级，节选）

```python
# domain/types.py —— 叶子，纯类型
@dataclass(frozen=True)
class Chunk: id: int; doc_id: str; text: str; byte_start: int; byte_end: int
@dataclass(frozen=True)
class EvidenceAnchor: chunk_id: int; utf16_start: int; utf16_end: int; byte_start: int; byte_end: int
@dataclass(frozen=True)
class Claim: id: str; text: str; anchor: EvidenceAnchor | None
class EvidenceMode(StrEnum): STRICT = "strict"; LENIENT = "lenient"

# infra/hardware.py
@dataclass(frozen=True)
class HardwareProfile: total_bytes: int; avail_bytes: int; threads: int  # 已钳到 [2,4]
def detect() -> HardwareProfile: ...
def require_free(p: HardwareProfile, need_bytes: int) -> None: ...  # 不足抛 InsufficientMemory

# infra/db.py
def connect(db_path: Path) -> sqlite3.Connection: ...   # 开 FTS5 + load vec0
def migrate(conn) -> None: ...

# infra/modelhub.py
@dataclass(frozen=True)
class ModelRef: name: str; kind: Literal["llm","embed"]; source: Literal["ollama","hf-mirror","modelscope"]; sha256: str
def ensure(ref: ModelRef) -> Path: ...      # 缺则拉取、在则校验 sha256
def list_models() -> list[ModelRef]: ...

# infra/infer.py —— LLM 可驱逐
class LlmClient(Protocol):
    def chat(self, messages, *, stream: bool, keep_alive: str, num_ctx: int, num_thread: int) -> Iterator[str] | str: ...
    def unload(self) -> None: ...
def connect_ollama(base_url: str = "http://127.0.0.1:11434") -> LlmClient: ...

# infra/embed.py —— 常驻
class Embedder(Protocol):
    dim: int
    def encode(self, texts, *, batch: int = 8) -> "NDArray[np.float32]": ...
def load_local_onnx(ref: ModelRef, threads: int) -> Embedder: ...

# repositories/index_repo.py
def open_indexes(conn, dim: int) -> tuple[VectorIndex, LexicalIndex]: ...
def get_chunk(conn, chunk_id: int) -> Chunk: ...

# repositories/trace_repo.py
class Trace:
    def __init__(self, conn, *, retention_days: int = 180) -> None: ...
    def append(self, span: TraceSpan) -> HashLink: ...
    def verify(self) -> None: ...   # 失败抛 tamper-detected
    def is_intact(self) -> bool: ...

# domain/fusion.py
def fuse(lexical: RankList, semantic: RankList, rerank: RankList = (), w: float = 0.0) -> list[tuple[int,float]]: ...
RRF_K: int = 60; RERANK_WEIGHT: float = 0.5; PRIMARY_PRIORITY: int = 2

# domain/evidence.py
class EvidenceGate:
    def __init__(self, mode: EvidenceMode = EvidenceMode.STRICT) -> None: ...
    def gate(self, claims: Sequence[Claim]) -> GateOutcome: ...
def slice_evidence(anchor: EvidenceAnchor, chunk_text: str) -> str: ...  # byte↔utf16 交叉校验

# services/ingest.py
def ingest_file(conn, encoder: Embedder, path: Path, *, chunk_size: int, overlap: int) -> IngestReport: ...

# services/retrieve.py
@dataclass(frozen=True)
class RetrievalResult: vector: RankList; lexical: RankList; chunks: dict[int, Chunk]
def retrieve(conn, encoder: Embedder, query: str, *, k_vec: int = 50, k_lex: int = 50) -> RetrievalResult: ...

# services/agent.py —— 唯一聚合层
@dataclass(frozen=True)
class Answer: text: str; citations: tuple[EvidenceAnchor, ...]; mode: EvidenceMode; refused: bool
def answer(conn, encoder, llm: LlmClient, query: str, *, mode: EvidenceMode = EvidenceMode.STRICT) -> Answer: ...

# services/eval.py
def run_golden(conn, encoder, llm, goldens: Sequence[Golden]) -> EvalReport: ...
```

> **跨语言 canonical 序列化必须钉死字节级定义**：JS `JSON.stringify` 不转义非 ASCII，Python `json.dumps` 默认转义（需 `ensure_ascii=False`）→ 不钉死则两语言算出不同 hash。Tekmor 作为移植目标，统一用 `ensure_ascii=False` + 稳定 key 顺序，并把 aetheros 的 `kernel.test.ts` 对抗性 fixture 原样搬为黄金向量锁死行为等价。

## 6. 验收标准（AC-01..AC-14，EARS 格式，源自 PRD）

| AC | 类别 | 要求（摘要） |
|---|---|---|
| AC-01 | 离线底线 | 未配置云提供商时，ingest→retrieve→cite→answer 全流程**零出站请求**；出站计数器真实计数（非硬编码 0） |
| AC-02 | CPU 线程 | 初始化本地推理时 `autoThreads()` 钳到 [2,4] |
| AC-03 | 防回退 | 任何改动使 `autoThreads(n)` 返回 [2,4] 之外 → 测试具名失败 |
| AC-04 | 证据锚定 | 渲染答案 claim 时附加 citation 解析到具体 chunk id + 字符偏移，可点击回原文 |
| AC-05 | 无证据不输出 | claim 无法绑定检索 chunk span → 拦截该 claim，显式 evidence-gap 标记（strict 默认） |
| AC-06 | 引用可信 | citation 解析到不支持该 claim 的 chunk → 标 citation-unverified，不呈现实为 grounded |
| AC-07 | 检索融合 | rerank 启用时，融合为第三路信号 w=0.5 与首阶段 RRF 结果融合（不直接采用重排顺序） |
| AC-08 | 对抗不变量 | 全倒序 reranker 注入时，最终 top-1 仍是首阶段融合冠军（w 严格 <1） |
| AC-09 | 轨迹可重建 | 完整重建 输入/检索 chunk/工具调用/LLM 原文/最终输出（不能只有 `trace.length >= 4`） |
| AC-10 | 增量索引 | 文档内容 hash 未变 → 跳过重嵌 |
| AC-11 | 中文兜底 | 中文查询 top-1 低于相关阈值 → 答「未找到相关文档」而非生成无依据答案 |
| AC-12 | 单文件控制台 | `file://` 离线打开 HTML 渲染完整流程，**无需 server** |
| AC-13 | 端口/模型降级 | 默认端口不可用 → 回退 8765/8801/9000；模型文件缺失 → loader 保持 retryable 直至文件存在 |
| AC-14 | 证据模式可见 | `evidence.mode=lenient` 在 UI 与每条 trace 记录**永久标记**（lenient 只能显式开启） |

## 7. 构建可复现与质量门禁

- **版本锁定**：`uv.lock`（Python 依赖，锁到精确版本）+ `requirements.lock`（发布用）+ `Dockerfile` + `compose.yaml`（可选隔离）。
- **一键复现**：`uv sync --frozen` 安装锁定依赖；`uv run tekmor doctor` 自诊断并修复依赖冲突 / 编译失败 / 运行时错误（移植 aetheros 的 harness 思路：offline-guard 移植为 Python 版，拦截任何出站；`check-icons` / `check-policy` 移植为 uv 版 CI 门禁）。
- **门禁链**：`lint → typecheck → build → test:offline → verify:demo`（demo 引擎移植为单文件 HTML 自检）。
- **零出站验证**：offline-guard 移植后，CI 在断网环境下跑 `test:offline`，断言 `getOutbound() === 0`。

## 8. 实施前置条件（进入 Phase 2 前必须清的 blocking）

1. **【内存·实测证伪】** 宣称「端到端可实际运行」与当前 1.04–1.46GB 空闲冲突。MVP 不可运行的部分（F1 的 LLM 半边）按 AC-14 降级；用户需释放至 ≥5GB 空闲才能跑满 3B 档。
2. **【语言·已裁决】** 本 Spec 是 **Tekmor（Python）的 Spec**，不是 aetheros 的 TS Spec；aetheros 仅作只读参考源。
3. **【复用方式·已裁决】** Spec 明确写「移植 fusion/evidence/trace 到 Python + 复用语言无关文档资产」；Tekmor 实现修复版，不把 aetheros 当依赖引入。

## 9. 待用户确认事项（本次提交方案后）

- 默认档：拉 `qwen2.5:3b`（≈1.9GB 下载）还是改判已缓存的 `qwen3:4b`（峰值升到 3.7GB，需更多内存）？
- 引入 `evolver`（F7 Agent 层自演进）是否进 MVP 还是严格 P2？
- `docs/design/` 与 aetheros 的 P1 冲突（icons.manifest.ts 五态与 icon-semantics.md §4 不一致）— 由 Tekmor 从 §4 生成下游，aetheros 侧仅记录，不在此修。

---
*本草案综合 PM（竞品/命名/RICE/EARS）、架构师（复用裁决/选型/内存预算/接口）、设计师（设计系统继承/单文件控制台）三路 Phase 1 调研；所有版本号与 wheel 可用性均经本机实测或 PyPI 实测。*
