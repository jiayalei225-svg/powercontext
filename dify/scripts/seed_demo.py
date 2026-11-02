# -*- coding: utf-8 -*-
"""给评审准备一个「已经玩过两局、第三局进行中」的演示档案。

执行后，在 Dify 开始表单里把「记忆 ID」填成 demo，就能：
- 第一句话输入 `继续`：直接接上第三局（白天，预言家已验过 3 号）；
- 或输入 `开始游戏`：带着前两局的 NPC 记忆开新局。

脚本只写 PowerContext，不依赖 Dify。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import moonfall  # noqa: E402


def player_row(seat, role, alive=True):
    return {"seat": seat, "role": role, "alive": alive, "claim": "", "revealed": True}


def match_one():
    return {
        "no": 1,
        "gid": "demo-seed-1",
        "role": "wolf",
        "winner": "wolf",
        "result": "win",
        "days": 3,
        "player_alive": True,
        "betrayed": [2, 4],
        "defended": [3],
        "impressions": {"2": -2, "3": 1, "4": -2, "5": -1, "6": -1, "7": -1, "8": 0},
        "highlight": "你当狼人骗过了整个镇子。",
        "eclipse": 88,
        "quote": "月蚀镇不记仇，它只记账。",
        "post_mortem": ["第 2 夜：3 号死亡。", "第 3 天：5 号被放逐，身份是女巫。"],
    }


def match_two():
    return {
        "no": 2,
        "gid": "demo-seed-2",
        "role": "seer",
        "winner": "wolf",
        "result": "lose",
        "days": 2,
        "player_alive": False,
        "betrayed": [3],
        "defended": [2],
        "impressions": {"2": 1, "3": -1, "4": 0, "5": -1, "6": -1, "7": -1, "8": 0},
        "highlight": "你没能活着看到月蚀结束。",
        "eclipse": 72,
        "quote": "下一次月蚀，记得先看谁的鞋底有泥。",
        "post_mortem": ["第 1 夜：4 号死亡。", "第 2 天：你被放逐，狼人获胜。"],
    }


def ended_state(match):
    return {
        "v": 1,
        "gid": match["gid"],
        "status": "ended",
        "phase": "ended",
        "turn": 20 + int(match["no"]),
        "day": match["days"],
        "match_no": match["no"],
        "player_name": "演示玩家",
        "player": {"seat": 1, "name": "演示玩家"},
        "players": [
            player_row(1, match["role"], alive=match.get("player_alive", True)),
            player_row(2, "villager", alive=True),
            player_row(3, "villager", alive=False),
            player_row(4, "hunter", alive=False),
            player_row(5, "witch", alive=False),
            player_row(6, "wolf", alive=True),
            player_row(7, "wolf", alive=True),
            player_row(8, "seer", alive=True),
        ],
        "match": match,
    }


def remember(client, scope_id, text, reason):
    response = client.post(
        "/v1/memory/remember",
        json={"scope_id": scope_id, "kind": "save", "text": text, "reason": reason},
    )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(description="写入月蚀镇 demo 记忆")
    parser.add_argument("--base", default="http://127.0.0.1:8099")
    parser.add_argument("--memory-id", default="demo")
    parser.add_argument("--force", action="store_true", help="已有 demo 记忆时仍然再写一份")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base.rstrip("/"), timeout=30)
    health = client.get("/health/ready")
    health.raise_for_status()

    scope = client.post(
        "/v1/scopes",
        json={
            "title": "月蚀镇·狼人杀玩家档案",
            "summary": "保存玩家在月蚀镇的每一局身份、胜负、NPC 关系与对局存档，供跨会话续局和 NPC 记忆复用。",
            "idempotency_key": "moonfall:user:" + args.memory_id,
        },
    )
    scope.raise_for_status()
    scope_id = scope.json()["scope_id"]

    listing = client.post("/v1/memory/entries/list", json={"scope_id": scope_id, "limit": 100})
    listing.raise_for_status()
    entries = listing.json().get("entries") or []
    already = any('"gid":"demo-seed-' in (entry.get("text") or "") for entry in entries)
    if already and not args.force:
        print(f"demo 记忆已存在，跳过写入。scope_id={scope_id}")
        print("如需重新生成，先停止 PowerContext 并删除数据目录，或换一个 --memory-id。")
        return 0

    one = ended_state(match_one())
    two = ended_state(match_two())
    text_one = json.dumps(one, ensure_ascii=False, separators=(",", ":"))
    text_two = json.dumps(two, ensure_ascii=False, separators=(",", ":"))
    remember(client, scope_id, text_one, "演示档案：第一局（狼人胜）")
    remember(client, scope_id, text_two, "演示档案：第二局（预言家败）")

    recall = json.dumps(
        {
            "entries": [
                {"kind": "save", "text": text_one},
                {"kind": "save", "text": text_two},
            ]
        },
        ensure_ascii=False,
    )
    active_text = None
    for _attempt in range(30):
        setup = moonfall.handle_turn("开始游戏", scope_id, recall, "演示玩家", args.memory_id)
        role = moonfall.handle_turn(
            "预言家",
            scope_id,
            json.dumps(
                {
                    "entries": [
                        {"kind": "save", "text": text_one},
                        {"kind": "save", "text": text_two},
                        {"kind": "save", "text": setup["save_text"]},
                    ]
                },
                ensure_ascii=False,
            ),
            "演示玩家",
            args.memory_id,
        )
        active = moonfall.handle_turn(
            "查 3",
            scope_id,
            json.dumps(
                {
                    "entries": [
                        {"kind": "save", "text": text_one},
                        {"kind": "save", "text": text_two},
                        {"kind": "save", "text": setup["save_text"]},
                        {"kind": "save", "text": role["save_text"]},
                    ]
                },
                ensure_ascii=False,
            ),
            "演示玩家",
            args.memory_id,
        )
        state = json.loads(active["save_text"])
        seat3 = next((item for item in state["players"] if item["seat"] == 3), {})
        if state.get("phase") == "day" and seat3.get("role") == "wolf" and seat3.get("alive"):
            state["gid"] = "demo-active"
            state["created"] = datetime.now().timestamp()
            state["updated"] = datetime.now().timestamp()
            active_text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
            break
    if active_text is None:
        raise RuntimeError("could not generate a demo state where seat 3 is a wolf")
    remember(client, scope_id, active_text, "演示档案：第三局进行中（预言家，第一天，3 号是狼）")

    final = client.post("/v1/memory/entries/list", json={"scope_id": scope_id, "limit": 100})
    final.raise_for_status()
    count = len(final.json().get("entries") or [])
    print("demo 记忆已写入")
    print(f"  scope_id  = {scope_id}")
    print(f"  memory_id = {args.memory_id}")
    print(f"  entries   = {count}")
    print("")
    print("在 Dify 开始表单填写：")
    print(f"  你的称呼 = 演示玩家")
    print(f"  记忆 ID  = {args.memory_id}")
    print("第一句输入 `继续` 接上第三局；输入 `重开确认` 放弃第三局，再输入 `预言家/女巫/...` 开新局。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
