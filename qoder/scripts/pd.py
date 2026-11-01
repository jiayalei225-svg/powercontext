"""Small HTTP client for PaperDesk: python scripts/pd.py <command>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

BASE = os.environ.get("PAPERDESK_URL", "http://127.0.0.1:8080").rstrip("/")


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=180)


def _dump(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_health(_: argparse.Namespace) -> None:
    with _client() as client:
        _dump(client.get("/api/health").json())


def cmd_list(_: argparse.Namespace) -> None:
    with _client() as client:
        payload = client.get("/api/papers").json()
    for paper in payload["papers"]:
        code = " · 开源" if paper["has_code"] else ""
        print(
            f"{paper['paper_id']}  {paper['year'] or '----'}  {paper['venue']:<12s}  "
            f"{paper['title']}  [{paper['chunks']} 片段 / {paper['pages']} 页]{code}"
        )
    print(f"共 {payload['total']} 篇")


def cmd_search(args: argparse.Namespace) -> None:
    body = {
        "query": args.query,
        "limit": args.limit,
        "year_from": args.year_from,
        "year_to": args.year_to,
        "venues": args.venue or None,
        "field": args.field,
        "has_code": True if args.code else None,
        "use_memory": not args.no_memory,
    }
    with _client() as client:
        response = client.post("/api/search", json=body)
    if response.status_code != 200:
        raise SystemExit(f"检索失败：{response.status_code} {response.text}")
    payload = response.json()
    if args.json:
        _dump(payload)
        return
    print(f"检索：{payload['query']}  策略={payload['strategy']}  用时={payload['elapsed_ms']}ms  命中={payload['total']}")
    print(f"词项：{'、'.join(payload['terms']) or '无'}   字面锚点：{payload['literal'] or '无'}")
    for note in payload["notes"]:
        print(f"记忆 · {note}")
    if not payload["results"]:
        print("没有命中。")
        return
    print("")
    for position, hit in enumerate(payload["results"], start=1):
        code = " · 有代码" if hit["has_code"] else ""
        print(f"{position}. {hit['title']}  ({hit['venue']}, {hit['year'] or '年份未知'}, p.{hit['page']}){code}")
        print(f"   {hit['snippet']}")
        print("")
    if not payload["memory_connected"]:
        print("提示：PowerContext 未连接，本次没有应用或记录记忆。")


def cmd_upload(args: argparse.Namespace) -> None:
    with _client() as client:
        for path_str in args.files:
            path = Path(path_str)
            with path.open("rb") as handle:
                response = client.post(
                    "/api/papers",
                    files={"file": (path.name, handle, "application/pdf")},
                )
            if response.status_code != 200:
                print(f"{path.name}: 失败 {response.status_code} {response.text}")
                continue
            payload = response.json()
            paper = payload["paper"]
            state = "已存在" if payload["duplicate"] else f"新增 {payload['added']} 片段"
            print(f"{path.name}: {state} -> {paper['paper_id']} 《{paper['title']}》")


def cmd_delete(args: argparse.Namespace) -> None:
    with _client() as client:
        response = client.delete(f"/api/papers/{args.paper_id}")
    print(response.status_code, response.text)


def cmd_prefs(args: argparse.Namespace) -> None:
    with _client() as client:
        if args.action == "show":
            _dump(client.get("/api/preferences").json())
            return
        if args.action == "clear":
            payload = {"year_from": None, "venues": [], "only_with_code": False, "field": None}
        else:
            payload = {
                "year_from": args.year_from,
                "venues": args.venue or [],
                "only_with_code": bool(args.code),
                "field": args.field,
            }
        response = client.put("/api/preferences", json=payload)
        if response.status_code != 200:
            raise SystemExit(f"保存失败：{response.status_code} {response.text}")
        _dump(response.json())


def cmd_memory(_: argparse.Namespace) -> None:
    with _client() as client:
        _dump(client.get("/api/memory").json())


def cmd_export(args: argparse.Namespace) -> None:
    body = {
        "query": args.query,
        "limit": args.limit,
        "year_from": args.year_from,
        "venues": args.venue or None,
        "field": args.field,
        "has_code": True if args.code else None,
    }
    path = "/api/search/export" if args.format == "md" else "/api/search/export.csv"
    with _client() as client:
        response = client.post(path, json=body)
    if response.status_code != 200:
        raise SystemExit(f"导出失败：{response.status_code} {response.text}")
    target = Path(args.output)
    target.write_bytes(response.content)
    print(f"已写入 {target}（{len(response.content)} 字节）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PaperDesk 命令行客户端")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="查看服务、索引与记忆状态").set_defaults(func=cmd_health)
    sub.add_parser("list", help="列出文献库").set_defaults(func=cmd_list)

    search = sub.add_parser("search", help="执行一次记忆感知的检索")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--year-from", type=int)
    search.add_argument("--year-to", type=int)
    search.add_argument("--venue", action="append")
    search.add_argument("--field")
    search.add_argument("--code", action="store_true")
    search.add_argument("--no-memory", action="store_true")
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    upload = sub.add_parser("upload", help="上传 PDF")
    upload.add_argument("files", nargs="+")
    upload.set_defaults(func=cmd_upload)

    delete = sub.add_parser("rm", help="删除一篇论文")
    delete.add_argument("paper_id")
    delete.set_defaults(func=cmd_delete)

    prefs = sub.add_parser("prefs", help="查看或保存检索偏好")
    prefs.add_argument("action", choices=["show", "set", "clear"])
    prefs.add_argument("--year-from", type=int)
    prefs.add_argument("--venue", action="append")
    prefs.add_argument("--field")
    prefs.add_argument("--code", action="store_true")
    prefs.set_defaults(func=cmd_prefs)

    sub.add_parser("memory", help="查看 PowerContext 记忆").set_defaults(func=cmd_memory)

    export = sub.add_parser("export", help="把检索结果导出为文件")
    export.add_argument("query")
    export.add_argument("--format", choices=["md", "csv"], default="md")
    export.add_argument("-o", "--output", required=True)
    export.add_argument("--limit", type=int, default=12)
    export.add_argument("--year-from", type=int)
    export.add_argument("--venue", action="append")
    export.add_argument("--field")
    export.add_argument("--code", action="store_true")
    export.set_defaults(func=cmd_export)

    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except httpx.HTTPError as exc:
        raise SystemExit(f"无法连接 {BASE}：{exc}") from exc


if __name__ == "__main__":
    main()
