"""End-to-end acceptance against a running PaperDesk server.

    python scripts/accept.py --base http://127.0.0.1:8080

Every step prints PASS/FAIL; a JSON report is written under runtime/accept/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "runtime" / "accept"


class Checks:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str) -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        self.steps.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            self.failed += 1


def search(client: httpx.Client, body: dict) -> dict:
    response = client.post("/api/search", json=body)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("PAPERDESK_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--samples", type=Path, default=ROOT / "samples")
    args = parser.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    with httpx.Client(base_url=args.base.rstrip("/"), timeout=240) as client:
        health = client.get("/api/health").json()
        checks.check(
            "服务健康",
            health.get("status") == "ok",
            f"version={health.get('version')} collection={health.get('index', {}).get('collection')}",
        )
        checks.check(
            "PowerContext 连接",
            health.get("memory", {}).get("connected") is True,
            f"scope={health.get('memory', {}).get('scope_id')}",
        )

        files = sorted(args.samples.glob("*.pdf"))
        for path in files:
            with path.open("rb") as handle:
                response = client.post(
                    "/api/papers",
                    files={"file": (path.name, handle, "application/pdf")},
                )
            payload = response.json() if response.status_code == 200 else {}
            paper = payload.get("paper") or {}
            checks.check(
                f"导入 {path.name}",
                response.status_code == 200 and bool(paper.get("paper_id")),
                f"{paper.get('title')} / {paper.get('chunks')} 片段 / 重复={payload.get('duplicate')}",
            )

        listing = client.get("/api/papers").json()
        checks.check("文献库数量", listing["total"] >= len(files), f"{listing['total']} 篇")
        if listing["papers"]:
            target = listing["papers"][0]["paper_id"]
            detail = client.get(f"/api/papers/{target}").json()
            checks.check(
                "论文详情",
                len(detail.get("chunk_details") or []) > 0,
                f"{detail.get('title')} 返回 {len(detail.get('chunk_details') or [])} 个片段",
            )

        result = search(client, {"query": "向量数据库里的混合检索", "limit": 6})
        checks.check(
            "混合检索召回",
            result["total"] > 0 and any("混合检索" in (hit["title"] or "") for hit in result["results"]),
            f"命中 {result['total']}，策略={result['strategy']}，{result['elapsed_ms']}ms",
        )
        checks.check(
            "搜索已写入记忆",
            result["memory_connected"] is True,
            f"memory_connected={result['memory_connected']}",
        )

        prefs = {"year_from": 2024, "venues": ["ACL"], "only_with_code": True, "field": "检索增强生成"}
        saved = client.put("/api/preferences", json=prefs)
        saved.raise_for_status()
        saved_payload = saved.json()
        checks.check(
            "保存记忆偏好",
            saved_payload.get("preferences") == prefs and bool(saved_payload.get("artifact")),
            f"artifact={saved_payload.get('artifact')} revision={saved_payload.get('revision')}",
        )

        recalled = search(client, {"query": "记忆路由", "limit": 6})
        applied = recalled.get("applied") or {}
        shapes = all(
            (hit["year"] or 0) >= 2024 and hit["venue"] == "ACL" and hit["has_code"] and hit["field"] == "检索增强生成"
            for hit in recalled["results"]
        )
        checks.check(
            "记忆偏好自动应用",
            len(applied) == 4 and len(recalled.get("notes") or []) == 4 and shapes,
            f"applied={sorted(applied)} notes={len(recalled.get('notes') or [])} hits={recalled['total']}",
        )

        override = search(
            client,
            {
                "query": "长文档分块与重排序",
                "limit": 5,
                "year_from": 2023,
                "venues": ["SIGIR"],
                "field": "信息检索",
                "has_code": False,
            },
        )
        override_ok = bool(override["results"]) and all(
            hit["venue"] == "SIGIR" and (hit["year"] or 0) >= 2023 for hit in override["results"]
        )
        checks.check(
            "显式条件覆盖记忆",
            override_ok and not override.get("applied"),
            f"filters={override['filters']} hits={override['total']}",
        )

        reset = client.put(
            "/api/preferences",
            json={"year_from": None, "venues": [], "only_with_code": False, "field": None},
        )
        reset.raise_for_status()
        after = client.get("/api/preferences").json()
        checks.check("清除记忆偏好", after.get("preferences") == {}, json.dumps(after.get("preferences"), ensure_ascii=False))

        markdown = client.post(
            "/api/search/export", json={"query": "混合检索", "limit": 5}
        )
        checks.check(
            "导出 Markdown",
            markdown.status_code == 200 and markdown.text.startswith("# PaperDesk 检索报告"),
            f"{len(markdown.content)} 字节",
        )
        csv_file = client.post("/api/search/export.csv", json={"query": "混合检索", "limit": 5})
        checks.check(
            "导出 CSV",
            csv_file.status_code == 200 and csv_file.content.startswith(b"\xef\xbb\xbf\xe5\xba\x8f\xe5\x8f\xb7"),
            f"{len(csv_file.content)} 字节",
        )

        history = client.get("/api/history").json()
        checks.check(
            "检索轨迹",
            history.get("connected") and len(history.get("searches") or []) >= 2,
            f"{len(history.get('searches') or [])} 条",
        )

        memory_snapshot = client.get("/api/memory").json()
        checks.check(
            "记忆快照",
            memory_snapshot.get("connected") is True and bool(memory_snapshot.get("scope_id")),
            f"scope={memory_snapshot.get('scope_id')} traces={len(memory_snapshot.get('searches') or [])}",
        )

        REPORT_DIR.joinpath("search.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        REPORT_DIR.joinpath("preferences-search.json").write_text(
            json.dumps(recalled, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        REPORT_DIR.joinpath("report.md").write_bytes(markdown.content)
        REPORT_DIR.joinpath("report.csv").write_bytes(csv_file.content)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base": args.base,
        "passed": len(checks.steps) - checks.failed,
        "failed": checks.failed,
        "steps": checks.steps,
    }
    (REPORT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print(f"共 {len(checks.steps)} 项，通过 {len(checks.steps) - checks.failed}，失败 {checks.failed}")
    print(f"报告：{REPORT_DIR / 'report.json'}")
    if checks.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
