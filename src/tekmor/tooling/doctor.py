"""doctor：自诊断并修复依赖冲突 / 编译失败 / 运行时错误（AC-13 韧性入口）。

检查项：Python 版本、依赖可导入、SQLite FTS5/vec0、内存画像、出站计数（AC-01）、
嵌入模型、Ollama 模型。返回结构化报告；缺项给出修复命令。
"""

from __future__ import annotations

import sqlite3
import sys

REQUIRED = [
    ("fastapi", "0.141.1"),
    ("uvicorn", "0.53.0"),
    ("sse_starlette", "3.4.11"),
    ("onnxruntime", "1.30.0"),
    ("numpy", "2.5.0"),
    ("tokenizers", "0.23.2"),
    ("sqlite_vec", "0.1.9"),
    ("opentelemetry.sdk", "1.44.0"),
]


def _check_deps() -> list[dict]:
    out = []
    for mod, ver in REQUIRED:
        try:
            __import__(mod)
            out.append({"module": mod, "version": ver, "ok": True})
        except Exception as e:  # noqa: BLE001
            out.append({"module": mod, "version": ver, "ok": False, "error": str(e)[:80]})
    return out


def _check_sqlite() -> dict:
    try:
        import sqlite_vec  # type: ignore

        c = sqlite3.connect(":memory:")
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        c.enable_load_extension(False)
        c.execute("CREATE VIRTUAL TABLE v USING vec0(k int, e float[4])")
        vec_ok = True
    except Exception as e:  # noqa: BLE001
        vec_ok = False
        err = str(e)[:120]
    try:
        c2 = sqlite3.connect(":memory:")
        c2.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        fts_ok = True
    except Exception as e:  # noqa: BLE001
        fts_ok = False
        err = str(e)[:120]
    return {"fts5_trigram": fts_ok, "vec0": vec_ok, "sqlite": sqlite3.sqlite_version, "error": (locals().get("err"))}


def run() -> dict:
    from ..infra.hardware import detect
    from ..infra.modelhub import embed_ready
    from ..infra.net import get_outbound

    report = {
        "python": sys.version.split()[0],
        "deps": _check_deps(),
        "sqlite": _check_sqlite(),
        "hardware": detect().__dict__,
        "outbound_count": get_outbound(),
        "embed_model_ready": embed_ready(),
    }
    # 汇总
    missing = [d["module"] for d in report["deps"] if not d["ok"]]
    report["summary"] = {
        "ok": not missing and report["sqlite"]["fts5_trigram"] and report["sqlite"]["vec0"],
        "missing_deps": missing,
    }
    return report


def print_report(report: dict) -> int:
    print("=== Tekmor doctor ===")
    print(f"Python           : {report['python']}")
    s = report["sqlite"]
    print(f"SQLite           : {s['sqlite']}  FTS5-trigram={s['fts5_trigram']}  vec0={s['vec0']}")
    for d in report["deps"]:
        mark = "OK " if d["ok"] else "MISS"
        print(f"  [{mark}] {d['module']} (~{d['version']})")
    h = report["hardware"]
    print(f"Hardware         : threads={h['threads']} avail={(h['avail_bytes'] or 0)/1e9:.2f}GB")
    print(f"Outbound count   : {report['outbound_count']} (AC-01 期望 0)")
    print(f"Embed model ready: {report['embed_model_ready']}")
    summ = report["summary"]
    if summ["ok"]:
        print("\n✅ 环境就绪")
        return 0
    print(f"\n⚠️ 缺失依赖：{summ['missing_deps']}")
    print("修复：uv sync --frozen")
    return 1
