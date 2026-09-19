"""Tekmor CLI 入口（cli 可脱离 server 单独跑）。

子命令：
  doctor            自诊断 + 修复指引
  models pull ...   获取嵌入/LLM 模型
  ingest <path>     导入知识库（增量，AC-10）
  serve             启动 FastAPI（端口自动回退，AC-13）
  eval  --golden   跑黄金集回归（命中率/拒答率/延迟）
"""

from __future__ import annotations

import argparse
import sys


def _cmd_doctor(_args: argparse.Namespace) -> int:
    from ..tooling.doctor import print_report, run

    return print_report(run())


def _cmd_models(args: argparse.Namespace) -> int:
    from ..infra.modelhub import ModelRef, ensure, pull_embed

    if args.target == "embed":
        path = pull_embed(ModelRef("Xenova/bge-small-zh-v1.5", "embed", "hf-mirror"))
        print(f"嵌入模型就绪：{path}")
        return 0
    # llm：交给 Ollama
    print(f"请执行：ollama pull {args.target}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from ..infra.db import connect, migrate
    from ..infra.embed import load_local_onnx
    from ..infra.hardware import auto_threads
    from ..infra.modelhub import ModelRef, ensure
    from ..services.ingest import ingest_file

    db = connect(args.db)
    migrate(db, 512)
    ref_path = ensure(ModelRef("Xenova/bge-small-zh-v1.5", "embed", "hf-mirror"))
    enc = load_local_onnx(ref_path, auto_threads())
    rep = ingest_file(db, enc, args.path, chunk_size=args.chunk_size, overlap=args.overlap)
    print(f"doc_id={rep.doc_id} chunks={rep.chunks} new={rep.new_chunks} skipped={rep.skipped}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from ..api.app import create_app
    from ..infra.hardware import auto_threads

    app = create_app(db_path=args.db, embed_threads=auto_threads(), llm_model=args.llm)
    # AC-13：默认端口不可用 → 回退 8765/8801/9000
    for port in [args.port, 8765, 8801, 9000]:
        try:
            uvicorn.run(app, host=args.host, port=port)
            return 0
        except OSError as e:
            if "address already in use" in str(e) or "10048" in str(e) or "98" in str(e):
                print(f"端口 {port} 被占用，尝试下一个...")
                continue
            raise
    print("所有候选端口均不可用")
    return 1


def _cmd_eval(args: argparse.Namespace) -> int:
    from ..infra.db import connect, migrate
    from ..infra.embed import load_local_onnx
    from ..infra.hardware import auto_threads
    from ..infra.modelhub import ModelRef, ensure
    from ..services.eval import EvalReport, load_golden, run_golden

    db = connect(args.db)
    migrate(db, 512)
    ref_path = ensure(ModelRef("Xenova/bge-small-zh-v1.5", "embed", "hf-mirror"))
    enc = load_local_onnx(ref_path, auto_threads())
    goldens = load_golden(args.golden)
    rep: EvalReport = run_golden(db, enc, goldens)
    print(f"total={rep.total} hit@3={rep.hit_at_3:.2%} hit@5={rep.hit_at_5:.2%} "
          f"refusal={rep.refusal_rate:.2%} latency={rep.latency_ms:.1f}ms")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tekmor", description="Tekmor 本地知识库与证据锚定平台")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="自诊断").set_defaults(func=_cmd_doctor)

    p_m = sub.add_parser("models", help="模型获取")
    p_m.add_argument("action", choices=["pull"], default="pull", nargs="?")
    p_m.add_argument("target", help="embed 或 ollama 模型名（如 qwen2.5:3b-instruct-q4_K_M）")
    p_m.set_defaults(func=_cmd_models)

    p_i = sub.add_parser("ingest", help="导入知识库")
    p_i.add_argument("path")
    p_i.add_argument("--db", default="tekmor.db")
    p_i.add_argument("--chunk-size", type=int, default=512)
    p_i.add_argument("--overlap", type=int, default=64)
    p_i.set_defaults(func=_cmd_ingest)

    p_s = sub.add_parser("serve", help="启动服务")
    p_s.add_argument("--host", default="127.0.0.1")
    p_s.add_argument("--port", type=int, default=8000)
    p_s.add_argument("--db", default="tekmor.db")
    p_s.add_argument("--llm", default="qwen2.5:3b-instruct-q4_K_M")
    p_s.set_defaults(func=_cmd_serve)

    p_e = sub.add_parser("eval", help="黄金集回归")
    p_e.add_argument("--golden", required=True)
    p_e.add_argument("--db", default="tekmor.db")
    p_e.set_defaults(func=_cmd_eval)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
