"""End-to-end acceptance against a running PaperDesk server.

    python scripts/accept.py --base http://127.0.0.1:8080

Every step prints PASS/FAIL; a JSON report is written under docs/verification/.
The run leaves a four-field preference in PowerContext so a reviewer can open
the UI and see the memory that was just written.
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
REPORT_DIR = ROOT / "docs" / "verification"
PREF_MARK = "paperdesk2/prefs/v1|"


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


def latest_powercontext_pref(base_url: str) -> tuple[str, dict | None, str | None, int]:
    """Read the newest PaperDesk preference directly from PowerContext."""
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30) as pc:
        scope = pc.get("/v1/scopes/default").raise_for_status().json()["scope_id"]
        latest: tuple[float, dict, str | None] | None = None
        cursor: str | None = None
        pages = 0
        while True:
            body: dict = {"scope_id": scope, "kind": "preference", "limit": 100}
            if cursor:
                body["cursor"] = cursor
            data = pc.post("/v1/atomic-memory/list", json=body).raise_for_status().json()
            for item in data.get("items") or []:
                text = item.get("text") or ""
                if not text.startswith(PREF_MARK):
                    continue
                try:
                    payload = json.loads(text[len(PREF_MARK) :])
                except json.JSONDecodeError:
                    continue
                saved_at = float(payload.get("saved_at") or 0)
                if latest is None or saved_at > latest[0]:
                    artifact = (item.get("artifact") or {}).get("artifact_id")
                    latest = (saved_at, payload, artifact)
            pages += 1
            cursor = data.get("next_cursor")
            if not cursor:
                break
        if latest is None:
            return scope, None, None, pages
        clean = {key: value for key, value in latest[1].items() if key != "saved_at"}
        return scope, clean, latest[2], pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("PAPERDESK_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--powercontext", default=os.environ.get("POWERCONTEXT_URL", ""))
    parser.add_argument("--samples", type=Path, default=ROOT / "samples")
    args = parser.parse_args()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    with httpx.Client(base_url=args.base.rstrip("/"), timeout=240) as client:
        health = client.get("/api/health").json()
        memory_url = args.powercontext or health.get("memory", {}).get("url") or "http://127.0.0.1:18000"
        checks.check(
            "服务健康",
            health.get("status") == "ok",
            f"version={health.get('version')} collection={health.get('index', {}).get('collection')}",
        )
        checks.check(
            "PowerContext 连接",
            health.get("memory", {}).get("connected") is True,
            f"scope={health.get('memory', {}).get('scope_id')} url={memory_url}",
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

        pdf_ok = True
        pdf_detail = []
        for paper in listing["papers"]:
            paper_id = paper["paper_id"]
            detail = client.get(f"/api/papers/{paper_id}").json()
            file_response = client.get(f"/api/papers/{paper_id}/file")
            ok = (
                detail.get("has_pdf") is True
                and file_response.status_code == 200
                and file_response.content.startswith(b"%PDF")
            )
            pdf_ok = pdf_ok and ok
            pdf_detail.append(f"{paper_id}:{'ok' if ok else 'missing'}")
        checks.check(
            "原始 PDF 可读回",
            pdf_ok and len(pdf_detail) >= len(files),
            f"{len(pdf_detail)} 篇 · " + ", ".join(pdf_detail[:3]),
        )

        target = listing["papers"][0]["paper_id"] if listing["papers"] else ""
        detail = client.get(f"/api/papers/{target}").json() if target else {}
        checks.check(
            "论文详情",
            len(detail.get("chunk_details") or []) > 0,
            f"{detail.get('title')} 返回 {len(detail.get('chunk_details') or [])} 个片段",
        )

        # Make the baseline independent of preferences left by an earlier run.
        client.put(
            "/api/preferences",
            json={"year_from": None, "venues": [], "only_with_code": False, "field": None},
        ).raise_for_status()

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

        fresh = client.get("/api/preferences", params={"fresh": "true"}).json()
        checks.check(
            "清缓存后从 PowerContext 读回",
            fresh.get("connected") is True and fresh.get("preferences") == prefs,
            json.dumps(fresh.get("preferences"), ensure_ascii=False),
        )

        try:
            scope, pc_prefs, pc_artifact, pages = latest_powercontext_pref(memory_url)
            pc_ok = pc_prefs == prefs and pc_artifact == saved_payload.get("artifact")
            pc_detail = f"scope={scope} pages={pages} artifact={pc_artifact}"
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            pc_ok = False
            pc_detail = f"读取失败：{exc}"
        checks.check("绕过应用直接读 PowerContext", pc_ok, pc_detail)

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
        after = client.get("/api/preferences", params={"fresh": "true"}).json()
        checks.check(
            "清除记忆偏好",
            after.get("preferences") == {},
            json.dumps(after.get("preferences"), ensure_ascii=False),
        )

        restored = client.put("/api/preferences", json=prefs)
        restored.raise_for_status()
        restored_payload = restored.json()
        final_prefs = client.get("/api/preferences", params={"fresh": "true"}).json()
        checks.check(
            "重新保存并读回最终偏好",
            final_prefs.get("preferences") == prefs
            and final_prefs.get("preferences") == restored_payload.get("preferences"),
            f"artifact={restored_payload.get('artifact')} "
            + json.dumps(final_prefs.get("preferences"), ensure_ascii=False),
        )

        try:
            final_scope, final_pc_prefs, final_artifact, final_pages = latest_powercontext_pref(memory_url)
            final_pc_ok = (
                final_pc_prefs == prefs
                and final_artifact == restored_payload.get("artifact")
            )
            final_pc_detail = (
                f"scope={final_scope} pages={final_pages} artifact={final_artifact}"
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            final_pc_ok = False
            final_pc_detail = f"读取失败：{exc}"
        checks.check("最终偏好与 artifact 可从 PowerContext 直读", final_pc_ok, final_pc_detail)
        readback = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "powercontext": memory_url,
            "scope_id": final_scope if final_pc_ok else None,
            "pages": final_pages if final_pc_ok else None,
            "artifact": final_artifact if final_pc_ok else None,
            "preferences": final_pc_prefs if final_pc_ok else None,
        }
        REPORT_DIR.joinpath("powercontext-readback.json").write_text(
            json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
            "记忆快照保留偏好与轨迹",
            memory_snapshot.get("connected") is True
            and memory_snapshot.get("preferences") == prefs
            and any(item.get("artifact") == restored.json().get("artifact") for item in memory_snapshot.get("memories") or []),
            f"scope={memory_snapshot.get('scope_id')} prefs={len(memory_snapshot.get('preferences') or {})} "
            f"traces={len(memory_snapshot.get('searches') or [])} versions={len(memory_snapshot.get('memories') or [])}",
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
        "powercontext": memory_url,
        "passed": len(checks.steps) - checks.failed,
        "failed": checks.failed,
        "final_scope": readback["scope_id"],
        "final_artifact": readback["artifact"],
        "final_preferences": readback["preferences"],
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
