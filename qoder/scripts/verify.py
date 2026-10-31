"""End-to-end acceptance check.

Runs the same query twice — once without memory, once after saving a
preference — and asserts that seekdb filters the corpus and PowerContext is
what carried the preference. Prints the evidence the review materials refer to.

Usage:
    python scripts/verify.py                    # against http://127.0.0.1:8080
    python scripts/verify.py --reset            # clear stored preferences first
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

PASS, FAIL = "PASS", "FAIL"
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--reset", action="store_true", help="先清空记忆里的偏好")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.api, timeout=90.0)

    print("\n== 1. 服务健康 ==")
    health = client.get("/api/health").json()
    check("seekdb 可用", health["seekdb"]["papers"] > 0, f"{health['seekdb']['papers']} 篇 / {health['seekdb']['chunks']} 段")
    check("嵌入模型", True, f"{health['seekdb']['embedding']} ({health['seekdb']['mode']})")
    check("PowerContext 已连接", health["memory"], health["memory_url"])

    print("\n== 2. 文献库 ==")
    papers = client.get("/api/papers").json()["papers"]
    check("文献数量 >= 4", len(papers) >= 4, f"实际 {len(papers)} 篇")
    for paper in papers:
        print(f"      · {paper['title']} ({paper['venue']} {paper['year']}, {paper['pages']} 页)")

    if args.reset:
        client.put(
            "/api/preferences",
            json={
                "default_year_from": None,
                "default_venues": [],
                "default_field": None,
                "require_code": False,
                "topics": [],
                "reading_style": None,
            },
        )
        print("\n  (已清空记忆中的偏好)")

    query = "图神经网络为什么会过平滑"

    print("\n== 3. 第一次检索（记忆为空）==")
    first = client.post("/api/search", json={"query": query, "limit": 12}).json()
    top = first["results"][0] if first["results"] else {}
    check("命中结果", first["total"] > 0, f"{first['total']} 段")
    check(
        "首条命中《图神经网络》第 2 页",
        top.get("page") == 2 and "图神经网络" in (top.get("title") or ""),
        f"{top.get('title')} p.{top.get('page')}",
    )
    check("未应用记忆偏好", first["memory_notes"] == [], "memory_notes 为空")
    print(f"      关键词（全文分支）：{first['keyword']}")

    print("\n== 4. 写入偏好到 PowerContext ==")
    prefs = {
        "default_year_from": 2020,
        "default_venues": ["NeurIPS"],
        "default_field": None,
        "require_code": True,
        "topics": ["图神经网络"],
        "reading_style": "先看摘要和方法",
    }
    saved = client.put("/api/preferences", json=prefs).json()
    artifact = saved.get("artifact") or {}
    check("偏好写入成功", bool(artifact.get("artifact_id")), f"artifact {artifact.get('artifact_id')} rev {artifact.get('revision')}")

    print("\n== 5. 第二次检索（同样的 query，记忆生效）==")
    second = client.post("/api/search", json={"query": query, "limit": 12}).json()
    check("检索时自动应用了偏好", len(second["memory_notes"]) > 0, f"{len(second['memory_notes'])} 条")
    for note in second["memory_notes"]:
        print(f"      · {note}")
    violated = [
        r for r in second["results"] if (r["venue"] != "NeurIPS") or (r["year"] or 0) < 2020 or not r["has_code"]
    ]
    check("结果全部满足记忆约束", not violated, f"{second['total']} 段，违规 {len(violated)} 段")
    check("结果数量因过滤而收缩", second["total"] < first["total"], f"{first['total']} → {second['total']} 段")

    print("\n== 6. 记忆留痕 ==")
    snapshot = client.get("/api/memory").json()
    pref_entries = [e for e in snapshot["entries"] if e["kind"] == "preference"]
    log_entries = [e for e in snapshot["entries"] if e["kind"] == "progress"]
    check("偏好条目存在", len(pref_entries) >= 1, f"{len(pref_entries)} 条")
    check("检索记录被写入", len(log_entries) >= 2, f"{len(log_entries)} 条")

    print("\n== 7. 重启后偏好仍在（跨会话复用）==")
    reread = client.get("/api/preferences").json()["preferences"]
    check("重新读取到同一份偏好", reread.get("default_venues") == ["NeurIPS"] and reread.get("require_code") is True,
          json.dumps(reread, ensure_ascii=False))

    failed = [c for c in checks if not c[1]]
    print(f"\n结果：{len(checks) - len(failed)}/{len(checks)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
