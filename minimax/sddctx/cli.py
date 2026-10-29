"""sddctx 命令行入口。

    python -m sddctx.cli init
    python -m sddctx.cli ingest --specs-dir samples/specs/v1
    python -m sddctx.cli context --task samples/task.json
    python -m sddctx.cli state show --task-id ORD-FILTER-001
    python -m sddctx.cli stats
    python -m sddctx.cli serve --port 8123

输出统一为 JSON（UTF-8），便于被开发助手或脚本直接消费。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .ingest import ingest_all, ingest_code, ingest_specs, ingest_tests
from .selector import ContextBuilder
from .state import PowerContextState, StateUnavailable
from .store import SeekDBStore


def _emit(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass
    print(text)


def _store(settings: Settings) -> SeekDBStore:
    return SeekDBStore(settings.seekdb_path, query_log=settings.query_log)


def _state(settings: Settings) -> PowerContextState:
    return PowerContextState(settings.powercontext_url, settings.state_dir)


def _load_task(value: str) -> dict[str, Any]:
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


def cmd_init(args: argparse.Namespace) -> int:
    settings = Settings.load(specs_dir=args.specs_dir, project_root=args.project_root)
    store = _store(settings)
    result = ingest_all(store, project_root=settings.project_root, specs_dir=settings.specs_dir)
    state = _state(settings)
    health = state.health()
    scope_id = None
    if health["ok"]:
        try:
            scope_id = state.ensure_scope()
        except StateUnavailable as exc:
            health = {"ok": False, "detail": str(exc)}
    _emit(
        {
            "action": "init",
            "specs_dir": str(settings.specs_dir),
            "project_root": str(settings.project_root),
            "ingested": {
                "specs": result["specs"]["items"],
                "code": result["code"]["items"],
                "tests": result["tests"]["items"],
            },
            "seekdb": store.stats(),
            "powercontext": {"url": settings.powercontext_url, **health, "scope_id": scope_id},
        }
    )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = Settings.load(specs_dir=args.specs_dir, project_root=args.project_root)
    store = _store(settings)
    targets = args.targets or ["specs", "code", "tests"]
    result: dict[str, Any] = {}
    if "specs" in targets:
        result["specs"] = ingest_specs(store, settings.specs_dir, settings.project_root)
    if "code" in targets:
        result["code"] = ingest_code(store, settings.project_root)
    if "tests" in targets:
        result["tests"] = ingest_tests(store, settings.project_root)
    _emit({"action": "ingest", "targets": targets, "result": result, "seekdb": store.stats()})
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    settings = Settings.load(specs_dir=args.specs_dir, project_root=args.project_root)
    store = _store(settings)
    state = None
    if not args.no_state:
        state = _state(settings)
    builder = ContextBuilder(store, state, budget_bytes=args.budget)
    task = _load_task(args.task)
    context = builder.build(task)
    context["seekdb"] = {
        "backend": store.backend_name,
        "path": str(store.path),
        "counts": {kind: store.count(kind) for kind in ("spec", "code", "test")},
        "queries": store.query_count,
    }
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit(context)
    return 0


def cmd_state_show(args: argparse.Namespace) -> int:
    settings = Settings.load()
    record = _state(settings).load(args.task_id)
    _emit({"task_id": args.task_id, "found": record is not None, "record": record})
    return 0


def cmd_state_save(args: argparse.Namespace) -> int:
    settings = Settings.load()
    payload = json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file else {}
    record = _state(settings).save(args.task_id, payload, reason=args.reason)
    _emit({"saved": True, "record": record})
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = Settings.load()
    store = _store(settings)
    state = _state(settings)
    _emit(
        {
            "seekdb": store.stats(),
            "powercontext": {
                "url": settings.powercontext_url,
                **state.health(),
            },
            "paths": {
                "data_dir": str(settings.data_dir),
                "seekdb": str(settings.seekdb_path),
                "query_log": str(settings.query_log),
            },
        }
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    return serve(host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sddctx", description="SDD 工程上下文模块")
    parser.add_argument("--specs-dir", default=None, help="规格目录（默认 samples/specs/v1）")
    parser.add_argument("--project-root", default=None, help="业务工程根目录")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="建库并导入全部资料")
    init.set_defaults(func=cmd_init)

    ingest = sub.add_parser("ingest", help="重新导入资料")
    ingest.add_argument("targets", nargs="*", choices=["specs", "code", "tests"], default=None)
    ingest.set_defaults(func=cmd_ingest)

    context = sub.add_parser("context", help="为任务构造开发上下文")
    context.add_argument("--task", required=True, help="任务 JSON 文件或内联 JSON")
    context.add_argument("--out", default=None, help="把上下文写入文件")
    context.add_argument("--budget", type=int, default=24_000, help="上下文字节预算")
    context.add_argument("--no-state", action="store_true", help="不读取 PowerContext 状态")
    context.set_defaults(func=cmd_context)

    state = sub.add_parser("state", help="任务状态读写")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    show = state_sub.add_parser("show", help="读取任务状态")
    show.add_argument("--task-id", required=True)
    show.set_defaults(func=cmd_state_show)
    save = state_sub.add_parser("save", help="保存任务状态")
    save.add_argument("--task-id", required=True)
    save.add_argument("--file", default=None)
    save.add_argument("--reason", default="sddctx save")
    save.set_defaults(func=cmd_state_save)

    stats = sub.add_parser("stats", help="查看 seekdb 与 PowerContext 状态")
    stats.set_defaults(func=cmd_stats)

    serve_cmd = sub.add_parser("serve", help="以 HTTP 方式暴露上下文模块")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8123)
    serve_cmd.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
