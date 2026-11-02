# -*- coding: utf-8 -*-
"""月蚀镇 · 会记仇的 AI 狼人杀 —— 确定性游戏引擎。

这个文件同时承担两个角色：

1. 本地单元测试 / 演练脚本直接 import 它；
2. tools/build_dsl.py 会把整份源码嵌入 Dify Code 节点（追加 main 包装）。

因此这里只使用 Python 标准库，不写顶层副作用，也不依赖文件或网络。
所有随机决策都由 sha256 派生，保证「同一状态 + 同一输入」得到同一结果，
方便复盘、测试和评审复现。
"""

import hashlib
import json
import re
from datetime import datetime

VERSION = "1.0.0"

ROLE_NAMES = {
    "wolf": "狼人",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
    "villager": "村民",
}

ROLE_TEAM = {
    "wolf": "wolf",
    "seer": "good",
    "witch": "good",
    "hunter": "good",
    "villager": "good",
}

ROLE_ICONS = {
    "wolf": "🐺",
    "seer": "🔮",
    "witch": "🧪",
    "hunter": "🔫",
    "villager": "🌾",
}

ROLE_BRIEF = {
    "wolf": "每晚与狼队友共同选择一名好人击杀；白天伪装成好人。",
    "seer": "每晚查验一名玩家的阵营，是好人最重要的信息源。",
    "witch": "拥有一瓶解药和一瓶毒药，同一晚只能用一瓶。",
    "hunter": "被狼人杀害或被放逐时可以开枪带走一名玩家（被毒杀时不能开枪）。",
    "villager": "没有夜晚技能，靠发言和投票找出狼人。",
}

ROLE_ALIASES = {
    "wolf": ("狼人", "狼", "wolf", "werewolf", "狼王"),
    "seer": ("预言家", "预言", "查验", "seer", "验人"),
    "witch": ("女巫", "巫", "witch", "药"),
    "hunter": ("猎人", "猎", "hunter", "枪"),
    "villager": ("平民", "村民", "好人", "villager", "白板"),
    "random": ("随机", "随便", "都行", "random", "听天由命"),
}

NPCS = [
    {
        "seat": 2,
        "name": "老周",
        "title": "铁匠",
        "tag": "暴躁 · 护短 · 嘴硬心软",
        "style": "粗声粗气，短句，爱说“我抡铁锤的，不讲虚的”；被怀疑时会拍桌子。",
        "secret": "欠红姨三个月的酒钱，最怕她当众提。",
    },
    {
        "seat": 3,
        "name": "白露",
        "title": "修女",
        "tag": "温柔 · 记仇 · 话里有刺",
        "style": "轻声细语，句尾常带“愿月神宽恕你”，但每个字都像在记账。",
        "secret": "在教堂地窖里藏着一把不属于修女的刀。",
    },
    {
        "seat": 4,
        "name": "阿信",
        "title": "邮差",
        "tag": "话痨 · 八卦 · 胆小",
        "style": "语速快，爱说“我跟你们说，这事儿不对劲”，紧张时会重复别人的话。",
        "secret": "私拆过镇上所有人的信，包括你的。",
    },
    {
        "seat": 5,
        "name": "红姨",
        "title": "酒馆老板娘",
        "tag": "精明 · 爱赌 · 护店",
        "style": "嗓门亮，爱用买卖打比方：“在我店里，命也是要付账的。”",
        "secret": "酒馆地下室有一条通往镇外的暗道。",
    },
    {
        "seat": 6,
        "name": "皮皮",
        "title": "小丑",
        "tag": "疯癫 · 谜语人 · 偶尔一语中的",
        "style": "用第三人称说自己，爱押韵，爱突然安静；疯话里常藏着真话。",
        "secret": "他记得每一个来过月蚀镇的外乡人。",
    },
    {
        "seat": 7,
        "name": "沈先生",
        "title": "钟表匠",
        "tag": "冷静 · 算计 · 完美主义",
        "style": "慢条斯理，喜欢报时间，常说“时间会证明一切，通常证明我是对的”。",
        "secret": "他的钟表铺里有一座永远停在月蚀时刻的钟。",
    },
    {
        "seat": 8,
        "name": "小满",
        "title": "面包师",
        "tag": "胆小 · 讨好型 · 意外地敏锐",
        "style": "说话小声，常以“我、我烤了面包……”开头；被逼急了会突然说出一句很准的话。",
        "secret": "她每天夜里往井里放一块面包，不知道井里住着谁。",
    },
]

NPC_BY_SEAT = {item["seat"]: item for item in NPCS}
PLAYER_SEAT = 1

# 每个人对别人的一点私人偏见，让投票不总是整齐划一。
NPC_BIAS = {
    2: {7: 0.10, 5: -0.08},
    3: {6: 0.12, 2: -0.08},
    4: {2: 0.10, 3: -0.10},
    5: {3: 0.10, 4: -0.08},
    6: {7: 0.10, 2: -0.06},
    7: {6: 0.12, 3: -0.08},
    8: {2: 0.08, 5: -0.08},
}

ROLE_POOL = ["wolf", "wolf", "seer", "witch", "hunter", "villager", "villager", "villager"]

PHASE_NAMES = {
    "role_select": "选择身份",
    "night": "夜晚",
    "day": "白天",
    "hunter": "猎人开枪",
    "ended": "终局",
}

TEAM_NAMES = {"wolf": "狼人阵营", "good": "好人阵营"}

MAX_LOG = 10
MAX_SAVE_BYTES = 7600
MAX_TEXT = 260


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _clean(value, limit=MAX_TEXT):
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _sha(*parts):
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pick(seed, items):
    if not items:
        return None
    number = int(_sha(seed)[:12], 16)
    return items[number % len(items)]


def _chance(seed, percent):
    number = int(_sha(seed)[:12], 16) % 100
    return number < percent


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_json(raw, fallback):
    try:
        value = json.loads(raw or "")
        return value
    except Exception:
        return fallback


def _clamp(value, low, high):
    return max(low, min(high, value))


def _seat_list(text):
    return [int(item) for item in re.findall(r"\b([1-8])\b", str(text or ""))]


def _alive_seats(state):
    return [p["seat"] for p in state["players"] if p.get("alive")]


def _player(state):
    for item in state["players"]:
        if item["seat"] == PLAYER_SEAT:
            return item
    return {}

def _player_role(state):
    return _player(state).get("role", "villager")


def _seat(state, seat):
    for item in state["players"]:
        if item["seat"] == int(seat):
            return item
    return None


def _public_name(seat, player_name="你"):
    if int(seat) == PLAYER_SEAT:
        return player_name or "你"
    item = NPC_BY_SEAT.get(int(seat))
    return item["name"] if item else f"{seat}号"


def _public_label(state, seat):
    if int(seat) == PLAYER_SEAT:
        return f"{PLAYER_SEAT}号 你（{state.get('player_name') or '外乡人'}）"
    item = NPC_BY_SEAT.get(int(seat))
    if item:
        return f"{seat}号 {item['name']}（{item['title']}）"
    return f"{seat}号"


def _team_of(role):
    return ROLE_TEAM.get(role, "good")


def _role_name(role):
    return ROLE_NAMES.get(role, role)


def _npc(seat):
    return NPC_BY_SEAT.get(int(seat), {})


# ---------------------------------------------------------------------------
# 记忆：把 PowerContext 返回的 entries 还原成「对局存档 + 历史战绩」
# ---------------------------------------------------------------------------


def _parse_memory(recall_body):
    data = _safe_json(recall_body, {})
    entries = data.get("entries") if isinstance(data, dict) else []
    if not isinstance(entries, list):
        entries = []

    saves = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text") or ""
        state = _safe_json(text, None)
        if not isinstance(state, dict):
            continue
        gid = str(state.get("gid") or "")
        if not gid or not isinstance(state.get("players"), list):
            continue
        try:
            turn = int(state.get("turn") or 0)
        except Exception:
            turn = 0
        previous = saves.get(gid)
        if previous is None or turn >= int(previous.get("turn") or 0):
            saves[gid] = state

    active = [item for item in saves.values() if item.get("status") == "active"]
    ended = [item for item in saves.values() if item.get("status") == "ended"]

    active.sort(
        key=lambda item: (
            float(item.get("updated") or item.get("created") or 0),
            int(item.get("turn") or 0),
            str(item.get("gid")),
        )
    )
    ended.sort(key=lambda item: int((item.get("match") or {}).get("no") or 0))

    matches = []
    seen_match = set()
    for item in ended[-8:]:
        match = item.get("match")
        if isinstance(match, dict):
            key = int(match.get("no") or 0)
            if key in seen_match:
                continue
            seen_match.add(key)
            matches.append(match)

    return {
        "active": active[-1] if active else None,
        "matches": matches,
        "relations": _relations_from_matches(matches),
        "raw_count": len(entries),
    }


def _relations_from_matches(matches):
    relations = {item["seat"]: 0 for item in NPCS}
    for match in matches:
        impressions = match.get("impressions") or {}
        if not isinstance(impressions, dict):
            continue
        for key, value in impressions.items():
            try:
                seat = int(key)
                delta = int(value)
            except Exception:
                continue
            if seat in relations:
                relations[seat] = _clamp(relations[seat] + delta, -3, 3)
    return relations


def _memory_digest(matches):
    if not matches:
        return "你是第一次来月蚀镇，镇上的人还不认识你。"
    lines = []
    for match in matches[-4:]:
        no = match.get("no", "?")
        role = _role_name(match.get("role"))
        result = "获胜" if match.get("result") == "win" else "落败"
        highlight = _clean(match.get("highlight") or "", 60)
        lines.append(f"- 第 {no} 局：你当【{role}】，{result}。{highlight}")
    relations = _relations_from_matches(matches)
    echoes = []
    for seat in sorted(relations):
        delta = int(relations[seat])
        if delta <= -1:
            npc = _npc(seat)
            echoes.append(f"{npc.get('name', seat)}记得你坑过他（信任 {delta}）")
        elif delta >= 1:
            npc = _npc(seat)
            echoes.append(f"{npc.get('name', seat)}记得你帮过他（信任 +{delta}）")
    if echoes:
        lines.append("- " + "；".join(echoes[:3]) + "。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 新对局
# ---------------------------------------------------------------------------


def _new_state(scope_id, player_name, query, matches, relations, extra_nonce=""):
    name = _clean(player_name, 12) or "外乡人"
    match_no = len(matches) + 1
    nonce = datetime.now().strftime("%Y%m%d%H%M%S%f")
    gid = "mf" + _sha(scope_id, name, match_no, query, extra_nonce, nonce)[:10]

    players = [{"seat": PLAYER_SEAT, "role": "?", "alive": True, "claim": "", "revealed": False}]
    for item in NPCS:
        players.append({"seat": item["seat"], "role": "?", "alive": True, "claim": "", "revealed": False})

    return {
        "v": 1,
        "gid": gid,
        "status": "active",
        "created": datetime.now().timestamp(),
        "updated": datetime.now().timestamp(),
        "turn": 0,
        "phase": "role_select",
        "day": 0,
        "match_no": match_no,
        "player_name": name,
        "player": {"seat": PLAYER_SEAT, "name": name},
        "players": players,
        "relations": {str(key): value for key, value in relations.items()},
        "heat": {str(seat): 0.22 for seat in range(1, 9)},
        "witch": {"antidote": True, "poison": True},
        "seer_checks": [],
        "seer_claims": [],
        "night": {},
        "last_deaths": [],
        "votes": {},
        "last_vote": {},
        "claims": [],
        "pending_hunter": 0,
        "post_mortem": [],
        "chat": 0,
        "log": ["你推开了月蚀镇酒馆的门，门外的月亮缺了一角。"],
        "stats": {"lies": 0, "correct_votes": 0, "wrong_votes": 0, "defended": [], "accused": []},
        "match": None,
    }


def _assign_roles(state, player_role, seed):
    pool = list(ROLE_POOL)
    if player_role in pool:
        pool.remove(player_role)
    else:
        player_role = "villager"
        pool.remove("villager")

    number = int(_sha(seed + ":roles")[:16], 16)
    for index in range(len(pool) - 1, 0, -1):
        number = (number * 1103515245 + 12345) % 2147483648
        swap = number % (index + 1)
        pool[index], pool[swap] = pool[swap], pool[index]

    for item in state["players"]:
        if item["seat"] == PLAYER_SEAT:
            item["role"] = player_role
        else:
            item["role"] = pool.pop()

    state["phase"] = "night"
    state["day"] = 1
    state["turn"] = int(state.get("turn") or 0) + 1
    state["night"] = {"victim": 0, "wolf_target": 0, "saved": False, "poison": 0, "resolved": False}
    state["log"].append(f"你选择了身份：{_role_name(player_role)}。")
    return state


def _wolves(state, alive_only=True):
    return [
        item["seat"]
        for item in state["players"]
        if item.get("role") == "wolf" and (item.get("alive") or not alive_only)
    ]


def _good_alive(state):
    return [
        item["seat"]
        for item in state["players"]
        if item.get("alive") and _team_of(item.get("role")) == "good"
    ]


def _check_win(state):
    wolves = _wolves(state, alive_only=True)
    good = _good_alive(state)
    if not wolves:
        return "good"
    if len(wolves) >= len(good):
        return "wolf"
    return None


def _winner_name(winner):
    return TEAM_NAMES.get(winner, "未知")


# ---------------------------------------------------------------------------
# 渲染：把结构化场景变成 Markdown（LLM 不可用时的完整兜底）
# ---------------------------------------------------------------------------


def _board(state):
    lines = []
    for item in state["players"]:
        seat = item["seat"]
        if seat == PLAYER_SEAT:
            label = f"{seat}. 你（{state.get('player_name') or '外乡人'}）"
        else:
            npc = _npc(seat)
            label = f"{seat}. {npc.get('name', '?')}（{npc.get('title', '?')}）"
        status = "存活" if item.get("alive") else "死亡"
        if item.get("revealed") and item.get("role") not in ("?", None):
            status += f" · {_role_name(item.get('role'))}"
        if item.get("claim"):
            status += f" · 自称{_role_name(item.get('claim'))}"
        lines.append(f"{label} · {status}")
    return "\n".join(lines)


def _private_lines(state):
    role = _player_role(state)
    lines = [f"**你的身份：{ROLE_ICONS.get(role, '')} {_role_name(role)}**", ROLE_BRIEF.get(role, "")]
    if role == "wolf":
        mates = [seat for seat in _wolves(state) if seat != PLAYER_SEAT]
        if mates:
            lines.append("**你的狼队友：**" + "、".join(_public_label(state, seat) for seat in mates))
        else:
            lines.append("**你的狼队友：** 只剩你一个了。")
    if role == "witch":
        lines.append(
            "**药剂：** 解药%s · 毒药%s"
            % ("还在" if state["witch"].get("antidote") else "已用", "还在" if state["witch"].get("poison") else "已用")
        )
    checks = [item for item in state.get("seer_checks", []) if item.get("by") == PLAYER_SEAT]
    if checks:
        lines.append("**你的查验记录：**")
        for item in checks[-6:]:
            lines.append(f"- 第 {item.get('day', '?')} 夜：{item.get('seat')} 号 → {item.get('result')}")
    return "\n".join(line for line in lines if line)


def _memory_line(matches):
    if not matches:
        return ""
    return _memory_digest(matches)


def _scene_markdown(scene):
    parts = [f"# {scene.get('title') or '月蚀镇'}"]
    narration = scene.get("narration") or ""
    if narration:
        parts.append("\n".join("> " + line for line in narration.split("\n")))
    events = scene.get("events") or []
    if events:
        parts.append("## 📜 发生了什么\n" + "\n".join(f"- {item}" for item in events))
    speeches = scene.get("speeches") or []
    if speeches:
        block = ["## 🗣️ 发言"]
        for item in speeches:
            block.append(f"**{item.get('seat')} 号 {item.get('name')}**：{item.get('text')}")
        parts.append("\n\n".join(block))
    private = scene.get("private") or ""
    if private:
        parts.append("## 🎭 只有你知道\n" + private)
    if scene.get("board"):
        parts.append("## 👥 场上\n" + scene["board"])
    if scene.get("memory"):
        parts.append("## 🧠 记忆回响\n" + scene["memory"])
    if scene.get("hint"):
        parts.append("---\n" + scene["hint"])
    return "\n\n".join(parts)


def _npc_line(state, seat, target, mode, reason):
    npc = _npc(seat)
    name = npc.get("name", f"{seat}号")
    if mode == "claim_seer":
        role = _role_name(_seat(state, seat).get("role"))
        return f"我是预言家。昨晚我查了 {target} 号，他是狼。你们信不信由你，反正{name}把话放这儿。"
    if mode == "accuse":
        return f"我觉得 {target} 号有问题。{reason} 我抡铁锤的，不讲虚的。" if seat == 2 else f"{target} 号，你最好解释一下。{reason}"
    if mode == "defend":
        return f"别急着投我。{reason} 我要是狼，昨晚就不会活到现在。"
    if mode == "wolf_deflect":
        return f"现在最该解释的是 {target} 号。{reason}"
    return f"我先听听。{reason}"


# ---------------------------------------------------------------------------
# 场景构造
# ---------------------------------------------------------------------------


def _setup_scene(state, matches):
    memory = _memory_digest(matches)
    events = [
        "月蚀镇已经三天没有邮差出镇了。",
        "酒馆的门从外面被反锁，桌上留着八张身份牌。",
        "纸条上写着：月蚀结束前，找出藏在你们中间的狼。",
    ]
    scene = {
        "title": "🌒 月蚀镇 · 第一夜之前",
        "narration": "月亮像一枚生锈的硬币，挂在酒馆窗外。八个人围坐在长桌旁，谁也没有先动面前的酒。",
        "events": events,
        "speeches": [],
        "private": "",
        "board": "\n".join(
            [f"1. 你（{state.get('player_name') or '外乡人'}）· 身份未定"]
            + [
                f"{item['seat']}. {item['name']}（{item['title']}）· 身份未定"
                for item in NPCS
            ]
        ),
        "memory": memory if matches else "",
        "hint": (
            "### 🎭 选择你的身份\n"
            "| 身份 | 能力 | 难度 |\n|---|---|---|\n"
            "| 🔮 预言家 | 每晚查验一人阵营 | 推荐 |\n"
            "| 🧪 女巫 | 一瓶解药、一瓶毒药 | 推荐 |\n"
            "| 🔫 猎人 | 死亡时开枪带走一人 | 中等 |\n"
            "| 🌾 村民 | 没有技能，全靠嘴 | 困难 |\n"
            "| 🐺 狼人 | 每晚刀人，白天演戏 | 刺激 |\n\n"
            "回复 **预言家 / 女巫 / 猎人 / 村民 / 狼人 / 随机** 开始。\n"
            "（第一夜你不会被狼人杀害，放心选。）"
        ),
    }
    return scene


def _role_reprompt_scene(state, query):
    scene = _setup_scene(state, [])
    scene["title"] = "🌒 月蚀镇 · 身份牌还没翻"
    scene["narration"] = f"“{_clean(query, 40) or '……'}”\n\n没人听懂你的意思。桌上的身份牌在烛光里发亮。"
    scene["memory"] = ""
    return scene


def _night_prompt_scene(state, matches):
    role = _player_role(state)
    night = state.get("night") or {}
    victim = int(night.get("victim") or 0)
    events = ["烛火熄灭，酒馆陷入黑暗。"]
    if role == "seer":
        hint = "回复 `查 3`（2-8 中选一个活着的座位）。"
        private = _private_lines(state) + "\n\n**今晚你可以查验一个人。**"
    elif role == "witch":
        victim_text = _public_label(state, victim) if victim else "今晚没有人遇袭"
        events.append(f"你闻到血腥味：{victim_text} 今晚遇袭。")
        hint = "回复 `救` 使用解药，或 `毒 3` 使用毒药，或 `不救` 保留药剂。"
        private = _private_lines(state) + "\n\n**同一晚只能用一瓶药。**"
    elif role == "wolf":
        mates = [seat for seat in _wolves(state) if seat != PLAYER_SEAT]
        mate_text = "、".join(_public_label(state, seat) for seat in mates) or "（没有队友了）"
        events.append(f"你的狼队友：{mate_text}。")
        hint = "回复 `刀 3` 选择今晚的击杀目标（不能刀狼队友）。"
        private = _private_lines(state)
    else:
        hint = "夜里没有你的行动。回复 `天亮` 继续。"
        private = _private_lines(state)
    scene = {
        "title": f"🌒 第 {state.get('day', 1)} 夜 · 月蚀镇",
        "narration": "风从门缝里钻进来，像有人在数还剩几口气。",
        "events": events,
        "speeches": [],
        "private": private,
        "board": _board(state),
        "memory": _memory_line(matches),
        "hint": hint,
    }
    scene["brief"] = {
        "phase": "night",
        "turn": state.get("turn"),
        "day": state.get("day", 1),
        "player_role": role,
        "public_facts": events,
        "speaker_plan": [],
        "memory_digest": _memory_digest(matches),
        "instruction": "只写氛围，不要替玩家做决定。",
    }
    return scene


def _dawn_events(state):
    events = []
    deaths = state.get("last_deaths") or []
    if deaths:
        for seat in deaths:
            events.append(f"天亮时，{_public_label(state, seat)} 没有再醒来。")
    else:
        events.append("天亮时，所有人都还活着。")
    if state.get("hunter_shot"):
        events.append(f"猎人 {state['hunter_shot'].get('hunter')} 号开枪带走了 {state['hunter_shot'].get('target')} 号。")
    return events


def _speaker_plan(state, matches):
    alive = [seat for seat in _alive_seats(state) if seat != PLAYER_SEAT]
    if not alive:
        return []
    heat = state.get("heat") or {}
    ranked = sorted(alive, key=lambda seat: float(heat.get(str(seat), 0.2)), reverse=True)
    speakers = ranked[:3]
    plan = []
    for seat in speakers:
        npc = _npc(seat)
        target = next((item for item in ranked if item != seat), None)
        role = (_seat(state, seat) or {}).get("role")
        goal = "accuse"
        reason = "他昨天一直在带节奏。" if target else "我先听听。"
        if float(heat.get(str(seat), 0.2)) > 0.6:
            goal = "defend"
            reason = "你们把票都压在我身上，总得给我个说话的机会。"
        if role == "wolf":
            goal = "wolf_deflect"
        if role == "seer" and seat in state.get("seer_claims", []):
            checks = [item for item in state.get("seer_checks", []) if item.get("by") == seat]
            if checks:
                goal = "claim_seer"
                target = checks[-1].get("seat")
        plan.append(
            {
                "seat": seat,
                "name": npc.get("name", f"{seat}号"),
                "style": npc.get("style", ""),
                "goal": goal,
                "target": target,
                "reason": reason,
                "heat": round(float(heat.get(str(seat), 0.2)), 2),
            }
        )
    return plan


def _day_scene(state, matches, extra_events=None, include_dawn=True):
    events = _dawn_events(state) if include_dawn else []
    if extra_events:
        events.extend(extra_events)
    plan = _speaker_plan(state, matches)
    speeches = []
    for item in plan:
        seat = item["seat"]
        mode = item["goal"]
        target = item.get("target") or 0
        speeches.append(
            {
                "seat": seat,
                "name": item["name"],
                "text": _npc_line(state, seat, target, mode, item.get("reason") or ""),
            }
        )
    scene = {
        "title": f"🌅 第 {state.get('day', 1)} 天 · 月蚀镇",
        "narration": "天亮了。酒馆里没人说话，只有钟表匠的怀表在走。",
        "events": events,
        "speeches": speeches,
        "private": _private_lines(state),
        "board": _board(state),
        "memory": _memory_line(matches),
        "hint": "回复 `投 3` 投票放逐；也可以继续发言，例如“我觉得 2 号在带节奏”。\n输入 `重开确认` 可以放弃本局重新开始。",
    }
    scene["brief"] = {
        "phase": "day",
        "turn": state.get("turn"),
        "day": state.get("day", 1),
        "player_role": _player_role(state),
        "public_facts": events,
        "speaker_plan": plan,
        "memory_digest": _memory_digest(matches),
        "instruction": "为每位发言者写 1-2 句符合人设的中文台词，不能泄露未公开身份，不能编造新死亡。",
    }
    return scene


def _vote_scene(state, matches, tally, exiled, tie, extra_events):
    events = []
    if tie:
        events.append("投票平票，没有人被放逐。")
    elif exiled:
        role = (_seat(state, exiled) or {}).get("role")
        events.append(f"{_public_label(state, exiled)} 被放逐。身份公开：{_role_name(role)}。")
    if extra_events:
        events.extend(extra_events)
    speeches = []
    for voter in sorted(tally.keys()):
        target = tally[voter]
        if target:
            speeches.append(
                {
                    "seat": voter,
                    "name": "你" if voter == PLAYER_SEAT else _npc(voter).get("name", f"{voter}号"),
                    "text": f"我投 {target} 号。",
                }
            )
    scene = {
        "title": f"⚖️ 第 {state.get('day', 1)} 天 · 放逐投票",
        "narration": "红姨把一只空酒杯放在桌子中央：“一个一个说，投谁。”",
        "events": events,
        "speeches": speeches,
        "private": _private_lines(state),
        "board": _board(state),
        "memory": _memory_line(matches),
        "hint": "",
    }
    scene["brief"] = {
        "phase": "vote",
        "turn": state.get("turn"),
        "day": state.get("day", 1),
        "public_facts": events,
        "speaker_plan": [],
        "memory_digest": _memory_digest(matches),
        "instruction": "写 2-3 句投票后的氛围，不要改变投票结果。",
    }
    return scene


# ---------------------------------------------------------------------------
# 动作解析
# ---------------------------------------------------------------------------


def _extract_name(query):
    match = re.search(r"(?:我叫|我是|名字叫|叫我)\s*([^\s，,。.!！?？]{1,12})", query or "")
    if not match:
        return ""
    name = match.group(1)
    if name in ("狼人", "预言家", "女巫", "猎人", "村民", "好人", "外乡人"):
        return ""
    return _clean(name, 12)


def _parse_role(query):
    text = (query or "").lower()
    for role, aliases in ROLE_ALIASES.items():
        for alias in aliases:
            if alias.lower() in text:
                return role
    return ""


def _parse_target(state, query, allow_self=False, alive_only=True):
    seats = _seat_list(query)
    for seat in seats:
        item = _seat(state, seat)
        if not item:
            continue
        if not allow_self and seat == PLAYER_SEAT:
            continue
        if alive_only and not item.get("alive"):
            continue
        return seat
    return 0


def _parse_vote(query):
    if re.search(r"(?:弃票|不投|放弃投票|弃权)", query or ""):
        return -1
    match = re.search(r"(?:投票|投给|投|放逐|票|出)\s*(?:给|死|走|掉)?\s*([1-8])", query or "")
    if match:
        return int(match.group(1))
    return 0


# ---------------------------------------------------------------------------
# 夜晚
# ---------------------------------------------------------------------------


def _ai_wolf_target(state, seed):
    candidates = _good_alive(state)
    if not candidates:
        return 0
    if state.get("day", 1) == 1 and PLAYER_SEAT in candidates and len(candidates) > 1:
        candidates = [seat for seat in candidates if seat != PLAYER_SEAT]

    def score(seat):
        item = _seat(state, seat) or {}
        value = 0.0
        if seat in state.get("seer_claims", []):
            value += 6.0
        claim = item.get("claim") or ""
        if claim == "seer":
            value += 5.0
        elif claim == "witch":
            value += 3.0
        elif claim == "hunter":
            value += 1.0
        value += (int(_sha(seed, "wolf", seat)[:8], 16) % 100) / 100.0
        return value

    return sorted(candidates, key=score)[-1]


def _ai_seer_check(state, seed):
    seer = next((p for p in state["players"] if p.get("role") == "seer" and p.get("alive")), None)
    if not seer or seer["seat"] == PLAYER_SEAT:
        return
    checked = {item.get("seat") for item in state.get("seer_checks", []) if item.get("by") == seer["seat"]}
    candidates = [seat for seat in _alive_seats(state) if seat != seer["seat"] and seat not in checked]
    if not candidates:
        return
    heat = state.get("heat") or {}
    target = sorted(candidates, key=lambda seat: float(heat.get(str(seat), 0.2)))[-1]
    item = _seat(state, target) or {}
    result = "狼人" if item.get("role") == "wolf" else "好人"
    state.setdefault("seer_checks", []).append(
        {"by": seer["seat"], "day": state.get("day", 1), "seat": target, "result": result}
    )
    if result == "狼人":
        if seer["seat"] not in state.setdefault("seer_claims", []):
            state["seer_claims"].append(seer["seat"])


def _ai_witch_action(state, seed):
    witch = next((p for p in state["players"] if p.get("role") == "witch" and p.get("alive")), None)
    if not witch or witch["seat"] == PLAYER_SEAT:
        return
    night = state.get("night") or {}
    victim = int(night.get("victim") or 0)
    if state["witch"].get("antidote") and victim and victim != PLAYER_SEAT:
        percent = 55 if state.get("day", 1) == 1 else 35
        if _chance(_sha(seed, "witch-save", victim, state.get("day")), percent):
            night["saved"] = True
            state["witch"]["antidote"] = False
            return
    if state["witch"].get("poison") and state.get("day", 1) >= 2:
        if _chance(_sha(seed, "witch-poison", state.get("day")), 28):
            candidates = [seat for seat in _alive_seats(state) if seat != witch["seat"] and seat != victim]
            if candidates:
                heat = state.get("heat") or {}
                target = sorted(candidates, key=lambda seat: float(heat.get(str(seat), 0.2)))[-1]
                night["poison"] = target
                state["witch"]["poison"] = False


def _status_brief(state, seat, cause):
    npc = _npc(seat)
    return f"{seat}号 {npc.get('name', '')} 死了（{cause}）。"


def _hunter_prompt_scene(state, matches):
    alive = [seat for seat in _alive_seats(state) if seat != PLAYER_SEAT]
    scene = {
        "title": "🔫 猎人的最后一枪",
        "narration": "你听见自己的血滴在地板上。猎枪还在手里，枪膛里还有一颗子弹。",
        "events": ["你倒下了。猎人技能触发：你可以开枪带走一名玩家。"],
        "speeches": [],
        "private": _private_lines(state) + "\n\n**你还可以开枪一次。**",
        "board": _board(state),
        "memory": _memory_line(matches),
        "hint": "回复 `开枪 4`（或 `带走 4`）选择目标；也可以回复 `不开枪`。",
    }
    scene["brief"] = {
        "phase": "hunter",
        "day": state.get("day", 1),
        "public_facts": scene["events"],
        "speaker_plan": [],
        "memory_digest": _memory_digest(matches),
        "instruction": "写 2 句悲壮/黑色幽默的遗言氛围，不要替玩家选目标。",
    }
    return scene


def _start_night(state, matches, first=False):
    if not first:
        state["day"] = int(state.get("day") or 1) + 1
    state["phase"] = "night"
    state["chat"] = 0
    state["last_deaths"] = []
    state["night"] = {"victim": 0, "wolf_target": 0, "saved": False, "poison": 0, "resolved": False}
    role = _player_role(state)
    if role != "wolf":
        seed = _sha(state.get("gid"), state.get("day"), state.get("turn"))
        victim = _ai_wolf_target(state, seed)
        if state.get("day", 1) == 1 and victim == PLAYER_SEAT:
            alternatives = [seat for seat in _good_alive(state) if seat != PLAYER_SEAT]
            victim = alternatives[0] if alternatives else 0
        state["night"]["victim"] = victim
    return _night_prompt_scene(state, matches)


def _kill(state, seat, cause):
    item = _seat(state, seat)
    if not item or not item.get("alive"):
        return False
    item["alive"] = False
    state["log"].append(_status_brief(state, seat, cause))
    return True


def _after_deaths(state, matches, deaths, poisoned, seed):
    """处理猎人、胜负、玩家死亡后的自动收尾。返回 (scene, finished)。"""
    for seat in deaths:
        item = _seat(state, seat) or {}
        if item.get("role") != "hunter" or seat in poisoned:
            continue
        if seat == PLAYER_SEAT:
            state["phase"] = "hunter"
            state["pending_hunter"] = 1
            return _hunter_prompt_scene(state, matches), True
        candidates = [target for target in _alive_seats(state) if target != seat]
        if candidates:
            heat = state.get("heat") or {}
            target = sorted(candidates, key=lambda target: float(heat.get(str(target), 0.2)))[-1]
            _kill(state, target, "猎人开枪")
            state["hunter_shot"] = {"hunter": seat, "target": target}
            deaths.append(target)
            if target == PLAYER_SEAT and _player_role(state) == "hunter":
                state["phase"] = "hunter"
                state["pending_hunter"] = 1
                return _hunter_prompt_scene(state, matches), True

    winner = _check_win(state)
    if winner:
        return _finish(state, winner, matches), True

    if not _player(state).get("alive"):
        return _auto_resolve(state, matches, "你出局后，月蚀镇的故事还在继续。"), True

    state["phase"] = "day"
    state["last_deaths"] = list(dict.fromkeys(deaths))
    return _day_scene(state, matches), False


def _resolve_night(state, matches):
    role = _player_role(state)
    night = state["night"]
    seed = _sha(state.get("gid"), "night", state.get("day"), state.get("turn"))

    if role == "wolf" and int(night.get("wolf_target") or 0):
        night["victim"] = int(night["wolf_target"])

    victim = int(night.get("victim") or 0)
    if state.get("day", 1) == 1 and victim == PLAYER_SEAT and role != "wolf":
        alternatives = [seat for seat in _good_alive(state) if seat != PLAYER_SEAT]
        victim = alternatives[0] if alternatives else 0
        night["victim"] = victim

    if role != "witch":
        _ai_witch_action(state, seed)
    _ai_seer_check(state, seed)

    deaths = []
    poisoned = set()
    if victim and not night.get("saved"):
        if _kill(state, victim, "狼人袭击"):
            deaths.append(victim)
    poison = int(night.get("poison") or 0)
    if poison and _kill(state, poison, "女巫毒杀"):
        deaths.append(poison)
        poisoned.add(poison)

    state["last_deaths"] = list(dict.fromkeys(deaths))
    state["night"]["resolved"] = True

    scene, finished = _after_deaths(state, matches, deaths, poisoned, seed)
    return scene


def _handle_night(state, query, matches, mem):
    role = _player_role(state)
    text = query or ""
    night = state["night"]

    if re.search(r"(投票|放逐|我投|投给|投\s*[1-8])", text):
        scene = _night_prompt_scene(state, matches)
        scene["narration"] = "现在是夜晚，投票要等天亮。先完成今晚的行动。"
        return scene

    if role == "villager":
        if re.search(r"(天亮|继续|闭眼|等待|过|跳过)", text):
            return _resolve_night(state, matches)
        scene = _night_prompt_scene(state, matches)
        scene["narration"] = "夜里什么都看不见。你只能听见自己的心跳。\n\n回复 `天亮` 继续。"
        return scene

    if role == "hunter":
        if re.search(r"(天亮|继续|闭眼|等待|过|跳过)", text):
            return _resolve_night(state, matches)
        scene = _night_prompt_scene(state, matches)
        scene["narration"] = "你把猎枪放在手边，假装睡着。\n\n回复 `天亮` 继续。"
        return scene

    if role == "seer":
        if re.search(r"(不查|跳过|放弃|过)", text):
            state["log"].append("你放弃了今晚的查验。")
            return _resolve_night(state, matches)
        target = _parse_target(state, text)
        if not target:
            scene = _night_prompt_scene(state, matches)
            scene["narration"] = "你需要在 2-8 号里选一个活着的目标。\n\n回复 `查 3`。"
            return scene
        checked = {item.get("seat") for item in state.get("seer_checks", []) if item.get("by") == PLAYER_SEAT}
        if target in checked:
            scene = _night_prompt_scene(state, matches)
            scene["narration"] = f"你昨晚已经查过 {target} 号了。换一个目标。"
            return scene
        item = _seat(state, target) or {}
        result = "狼人" if item.get("role") == "wolf" else "好人"
        state.setdefault("seer_checks", []).append(
            {"by": PLAYER_SEAT, "day": state.get("day", 1), "seat": target, "result": result}
        )
        state["log"].append(f"你查验了 {target} 号：{result}。")
        return _resolve_night(state, matches)

    if role == "witch":
        if re.search(r"(不救|不毒|保留|过|跳过)", text):
            return _resolve_night(state, matches)
        if re.search(r"(救|解药)", text):
            if not state["witch"].get("antidote"):
                scene = _night_prompt_scene(state, matches)
                scene["narration"] = "解药已经用掉了。你只能选择毒人，或者不救。"
                return scene
            if not int(night.get("victim") or 0):
                scene = _night_prompt_scene(state, matches)
                scene["narration"] = "今晚没有人遇袭，解药没有用武之地。"
                return scene
            night["saved"] = True
            state["witch"]["antidote"] = False
            state["log"].append(f"你用解药救了 {night.get('victim')} 号。")
            return _resolve_night(state, matches)
        if re.search(r"(毒|毒药)", text):
            if not state["witch"].get("poison"):
                scene = _night_prompt_scene(state, matches)
                scene["narration"] = "毒药已经用掉了。"
                return scene
            target = _parse_target(state, text)
            if not target:
                scene = _night_prompt_scene(state, matches)
                scene["narration"] = "要毒谁？回复 `毒 3`，或者 `不救` 保留药剂。"
                return scene
            night["poison"] = target
            state["witch"]["poison"] = False
            state["log"].append(f"你对 {target} 号下了毒。")
            return _resolve_night(state, matches)
        scene = _night_prompt_scene(state, matches)
        scene["narration"] = "回复 `救`、`毒 3` 或 `不救`。"
        return scene

    if role == "wolf":
        target = _parse_target(state, text)
        if not target:
            scene = _night_prompt_scene(state, matches)
            scene["narration"] = "要刀谁？回复 `刀 3`（不能刀狼队友）。"
            return scene
        target_item = _seat(state, target) or {}
        if target_item.get("role") == "wolf":
            scene = _night_prompt_scene(state, matches)
            scene["narration"] = f"{target} 号是你的狼队友，不能刀。换一个目标。"
            return scene
        night["wolf_target"] = target
        state["log"].append(f"你和狼队友决定袭击 {target} 号。")
        return _resolve_night(state, matches)

    return _resolve_night(state, matches)


# ---------------------------------------------------------------------------
# 白天
# ---------------------------------------------------------------------------


def _apply_speech(state, query):
    text = _clean(query, 240)
    role = _player_role(state)
    seat = _parse_target(state, text, allow_self=True)
    events = [f"你说：“{text}”"]
    stats = state.setdefault("stats", {})
    heat = state.setdefault("heat", {})

    claim = _parse_role(text)
    if claim in ("seer", "witch", "hunter", "villager") and re.search(r"(我是|我跳|我起跳|我认)", text):
        state["claim"] = claim
        state.setdefault("claims", []).append({"day": state.get("day"), "seat": PLAYER_SEAT, "claim": claim})
        heat["1"] = float(heat.get("1", 0.3)) + 0.12
        events.append(f"你公开自称：{_role_name(claim)}。")
        if role == "wolf" and claim != "wolf":
            stats["lies"] = int(stats.get("lies") or 0) + 1

    positive = re.search(r"(好人|不是狼|保他|保她|我信|信任|捞)", text)
    negative = re.search(r"(是狼|狼人|有问题|带节奏|可疑|查杀|投他|投她|出他|出她|怀疑)", text)
    if seat:
        if negative and not positive:
            heat[str(seat)] = _clamp(float(heat.get(str(seat), 0.2)) + 0.18, 0, 1)
            stats.setdefault("accused", []).append(seat)
            events.append(f"你把矛头指向了 {seat} 号。")
        elif positive:
            heat[str(seat)] = _clamp(float(heat.get(str(seat), 0.2)) - 0.16, 0, 1)
            stats.setdefault("defended", []).append(seat)
            events.append(f"你替 {seat} 号说了话。")

    state["chat"] = int(state.get("chat") or 0) + 1
    return events


def _ai_vote(state, voter, seed):
    voter_item = _seat(state, voter) or {}
    candidates = [seat for seat in _alive_seats(state) if seat != voter]
    if not candidates:
        return 0
    heat = state.get("heat") or {}
    relations = state.get("relations") or {}

    def score(target):
        target_item = _seat(state, target) or {}
        value = float(heat.get(str(target), 0.2)) * 1.6
        value += float((NPC_BIAS.get(voter) or {}).get(target, 0.0))
        if target == PLAYER_SEAT:
            trust = int(relations.get(str(voter), 0))
            value += -0.18 - trust * 0.15
            if state.get("day", 1) == 1:
                value -= 1.0
        if voter_item.get("role") == "wolf":
            if target_item.get("role") == "wolf":
                value -= 5.0
            else:
                value += 0.25
        if voter_item.get("role") == "seer":
            checks = [item for item in state.get("seer_checks", []) if item.get("by") == voter]
            if any(item.get("seat") == target and item.get("result") == "狼人" for item in checks):
                value += 2.5
        value += (int(_sha(seed, "vote", voter, target)[:8], 16) % 100) / 133.0
        return value

    return sorted(candidates, key=score)[-1]


def _resolve_vote(state, player_vote, matches):
    votes = {}
    if player_vote > 0:
        votes[PLAYER_SEAT] = player_vote
    elif player_vote == 0:
        votes[PLAYER_SEAT] = 0

    seed = _sha(state.get("gid"), "vote", state.get("day"), state.get("turn"))
    for seat in _alive_seats(state):
        if seat == PLAYER_SEAT:
            continue
        votes[seat] = _ai_vote(state, seat, seed)

    counts = {}
    for target in votes.values():
        if target:
            counts[target] = counts.get(target, 0) + 1

    exiled = 0
    tie = False
    if counts:
        best = max(counts.values())
        winners = [seat for seat, count in counts.items() if count == best]
        if len(winners) == 1:
            exiled = winners[0]
        else:
            tie = True

    state["votes"] = {str(key): value for key, value in votes.items()}
    state["last_vote"] = {
        "day": state.get("day"),
        "votes": {str(key): value for key, value in votes.items()},
        "exiled": exiled,
        "tie": tie,
    }

    extra = []
    if exiled:
        item = _seat(state, exiled) or {}
        item["alive"] = False
        item["revealed"] = True
        stats = state.setdefault("stats", {})
        if player_vote > 0:
            if (_seat(state, player_vote) or {}).get("role") == "wolf":
                stats["correct_votes"] = int(stats.get("correct_votes") or 0) + 1
            else:
                stats["wrong_votes"] = int(stats.get("wrong_votes") or 0) + 1
            stats.setdefault("voted", []).append(player_vote)
            if player_vote == PLAYER_SEAT:
                pass
        for voter, target in votes.items():
            if target:
                heat = state.setdefault("heat", {})
                heat[str(target)] = _clamp(float(heat.get(str(target), 0.2)) + 0.06, 0, 1)

        if item.get("role") == "hunter":
            if exiled == PLAYER_SEAT:
                state["phase"] = "hunter"
                state["pending_hunter"] = 1
                scene = _hunter_prompt_scene(state, matches)
                return scene, True
            candidates = [target for target in _alive_seats(state) if target != exiled]
            if candidates:
                heat = state.get("heat") or {}
                target = sorted(candidates, key=lambda target: float(heat.get(str(target), 0.2)))[-1]
                _kill(state, target, "猎人开枪")
                state["hunter_shot"] = {"hunter": exiled, "target": target}
                extra.append(f"{exiled} 号猎人开枪带走了 {target} 号。")
                if target == PLAYER_SEAT and _player_role(state) == "hunter":
                    state["phase"] = "hunter"
                    state["pending_hunter"] = 1
                    return _hunter_prompt_scene(state, matches), True

    winner = _check_win(state)
    if winner:
        return _finish(state, winner, matches), True

    if not _player(state).get("alive"):
        return _auto_resolve(state, matches, "你被放逐后，月蚀镇的故事还在继续。"), True

    scene = _vote_scene(state, matches, votes, exiled, tie, extra)
    night_scene = _start_night(state, matches)
    merged = _merge_scene(scene, night_scene)
    return merged, False


def _merge_scene(first, second):
    merged = dict(first)
    merged["title"] = f"{first.get('title')} → {second.get('title')}"
    merged["events"] = list(first.get("events") or []) + list(second.get("events") or [])
    merged["speeches"] = list(first.get("speeches") or []) + list(second.get("speeches") or [])
    merged["private"] = second.get("private") or first.get("private") or ""
    merged["board"] = second.get("board") or first.get("board") or ""
    merged["memory"] = second.get("memory") or first.get("memory") or ""
    merged["hint"] = second.get("hint") or ""
    merged["brief"] = second.get("brief") or first.get("brief") or {}
    return merged


def _handle_day(state, query, matches, mem):
    text = query or ""
    vote = _parse_vote(text)

    if re.search(r"(重开|重来|新一局)", text):
        if re.search(r"(确认|确定|yes)", text):
            new_state = _new_state(
                mem.get("scope_id", ""),
                state.get("player_name"),
                text,
                mem.get("matches") or [],
                mem.get("relations") or {},
                "restart",
            )
            return _setup_response(new_state, mem)
        scene = {
            "title": "🌒 月蚀镇 · 确认重开",
            "narration": "旧的牌局还没结束。你确定要把这一局掀掉吗？",
            "events": ["当前对局会被放弃，历史记忆不会消失。"],
            "speeches": [],
            "private": "",
            "board": _board(state),
            "memory": "",
            "hint": "回复 `重开确认` 放弃本局；回复任意其他内容继续当前对局。",
        }
        scene["brief"] = _default_brief(state, scene, matches)
        return scene

    if vote == 0 and re.search(r"(投票|放逐)", text) and not _seat_list(text):
        scene = _day_scene(state, matches, include_dawn=False)
        scene["narration"] = "要投谁？回复 `投 3`（1–8 中活着的座位）。"
        return scene

    if vote != 0:
        target = abs(vote)
        if vote > 0:
            if target == PLAYER_SEAT:
                scene = _day_scene(state, matches, include_dawn=False)
                scene["narration"] = "你不能投自己。换一个目标。"
                return scene
            item = _seat(state, target)
            if not item or not item.get("alive"):
                scene = _day_scene(state, matches, include_dawn=False)
                scene["narration"] = f"{target} 号已经不在场上了。换一个目标。"
                return scene
        scene, _finished = _resolve_vote(state, vote, matches)
        return scene

    if re.search(r"^(继续|继续游戏|我回来了|在场|看看)$", text):
        scene = _day_scene(state, matches, include_dawn=False)
        scene["narration"] = "你回到桌边。所有人都还坐在原来的位置，但看你的眼神变了。"
        return scene

    if re.search(r"^(过|跳过|不发言|沉默|等待)$", text):
        state["chat"] = int(state.get("chat") or 0) + 1
        scene = _day_scene(state, matches, extra_events=["你选择了沉默。"], include_dawn=False)
        scene["narration"] = "你没有说话。桌上的目光在你身上停了一会儿，又移开了。"
        return scene

    events = _apply_speech(state, text)
    scene = _day_scene(state, matches, extra_events=events, include_dawn=False)
    if int(state.get("chat") or 0) >= 3:
        scene["hint"] = "已经聊得够久了。回复 `投 3` 投票放逐，或者继续发言。"
    return scene


# ---------------------------------------------------------------------------
# 自动收尾 / 终局
# ---------------------------------------------------------------------------


def _ai_night_round(state, events):
    state["phase"] = "night"
    state["night"] = {"victim": 0, "wolf_target": 0, "saved": False, "poison": 0, "resolved": False}
    seed = _sha(state.get("gid"), "auto-night", state.get("day"))
    victim = _ai_wolf_target(state, seed)
    state["night"]["victim"] = victim
    _ai_witch_action(state, seed)
    _ai_seer_check(state, seed)
    deaths = []
    if victim and not state["night"].get("saved"):
        if _kill(state, victim, "狼人袭击"):
            deaths.append(victim)
    poison = int(state["night"].get("poison") or 0)
    if poison and _kill(state, poison, "女巫毒杀"):
        deaths.append(poison)
    for seat in list(deaths):
        item = _seat(state, seat) or {}
        if item.get("role") == "hunter" and seat != poison:
            candidates = [target for target in _alive_seats(state) if target != seat]
            if candidates:
                heat = state.get("heat") or {}
                target = sorted(candidates, key=lambda target: float(heat.get(str(target), 0.2)))[-1]
                _kill(state, target, "猎人开枪")
                events.append(f"第 {state.get('day')} 夜：猎人 {seat} 号开枪带走了 {target} 号。")
                deaths.append(target)
    if deaths:
        events.append(f"第 {state.get('day')} 夜：{'、'.join(str(seat) + '号' for seat in dict.fromkeys(deaths))} 死亡。")
    else:
        events.append(f"第 {state.get('day')} 夜：平安夜。")
    state["last_deaths"] = list(dict.fromkeys(deaths))
    return _check_win(state)


def _ai_vote_round(state, events):
    votes = {}
    seed = _sha(state.get("gid"), "auto-vote", state.get("day"))
    for seat in _alive_seats(state):
        votes[seat] = _ai_vote(state, seat, seed)
    counts = {}
    for target in votes.values():
        if target:
            counts[target] = counts.get(target, 0) + 1
    exiled = 0
    if counts:
        best = max(counts.values())
        winners = [seat for seat, count in counts.items() if count == best]
        if len(winners) == 1:
            exiled = winners[0]
    if exiled:
        item = _seat(state, exiled) or {}
        item["alive"] = False
        item["revealed"] = True
        events.append(f"第 {state.get('day')} 天：{exiled} 号被放逐，身份是{_role_name(item.get('role'))}。")
        if item.get("role") == "hunter":
            candidates = [target for target in _alive_seats(state) if target != exiled]
            if candidates:
                heat = state.get("heat") or {}
                target = sorted(candidates, key=lambda target: float(heat.get(str(target), 0.2)))[-1]
                _kill(state, target, "猎人开枪")
                events.append(f"猎人 {exiled} 号开枪带走了 {target} 号。")
    else:
        events.append(f"第 {state.get('day')} 天：平票，无人被放逐。")
    return _check_win(state)


def _auto_resolve(state, matches, reason):
    events = [reason]
    state["post_mortem"] = []
    rounds = 0
    winner = None
    while state.get("status") == "active" and rounds < 8:
        rounds += 1
        winner = _ai_night_round(state, events)
        if winner:
            break
        winner = _ai_vote_round(state, events)
        if winner:
            break
        state["day"] = int(state.get("day") or 1) + 1
    if not winner:
        winner = _check_win(state) or "good"
    state["post_mortem"] = events
    return _finish(state, winner, matches, post_mortem=events)


def _match_summary(state, winner, post_mortem):
    role = _player_role(state)
    team = _team_of(role)
    result = "win" if team == winner else "lose"
    stats = state.get("stats") or {}
    accused = list(dict.fromkeys(int(seat) for seat in stats.get("accused") or [] if str(seat).isdigit()))
    defended = list(dict.fromkeys(int(seat) for seat in stats.get("defended") or [] if str(seat).isdigit()))
    voted = list(dict.fromkeys(int(seat) for seat in stats.get("voted") or [] if str(seat).isdigit()))
    betrayed = list(dict.fromkeys(accused + voted))

    impressions = {}
    for item in NPCS:
        seat = item["seat"]
        delta = 0
        if seat in betrayed:
            delta -= 1
        if seat in defended:
            delta += 1
        if role == "wolf" and result == "win":
            delta -= 1
        if role != "wolf" and result == "win" and (_seat(state, seat) or {}).get("role") != "wolf":
            delta += 1
        impressions[str(seat)] = _clamp(delta, -3, 3)

    player_alive = bool(_player(state).get("alive"))
    if result == "win" and role == "wolf":
        highlight = "你当狼人骗过了整个镇子。"
    elif result == "win" and player_alive:
        highlight = "你活到了最后，狼人被清出月蚀镇。"
    elif result == "win":
        highlight = "你倒下了，但你的阵营笑到了最后。"
    elif role == "wolf":
        highlight = "你的狼人伪装被拆穿了。"
    elif player_alive:
        highlight = "你活到了最后，却没看清谁在说谎。"
    else:
        highlight = "你没能活着看到月蚀结束。"

    day = int(state.get("day") or 1)
    deaths = sum(1 for item in state["players"] if not item.get("alive"))
    eclipse = _clamp(30 + day * 6 + deaths * 5 + int(stats.get("lies") or 0) * 6, 0, 100)

    match = {
        "no": int(state.get("match_no") or 1),
        "gid": state.get("gid"),
        "role": role,
        "winner": winner,
        "result": result,
        "days": day,
        "player_alive": bool(_player(state).get("alive")),
        "betrayed": betrayed,
        "defended": defended,
        "impressions": impressions,
        "highlight": highlight,
        "eclipse": eclipse,
        "quote": _pick(_sha(state.get("gid"), "quote"), [
            "月蚀镇不记仇，它只记账。",
            "死人不会说话，活人说的又不一定是真话。",
            "下一次月蚀，记得先看谁的鞋底有泥。",
            "你以为你在找狼，狼也在找你。",
        ]),
        "post_mortem": post_mortem[-6:] if post_mortem else [],
    }
    return match


def _finish(state, winner, matches, post_mortem=None):
    state["status"] = "ended"
    state["phase"] = "ended"
    state["winner"] = winner
    for item in state["players"]:
        item["revealed"] = True
    match = _match_summary(state, winner, post_mortem or [])
    state["match"] = match

    role = _player_role(state)
    result_text = "你赢了" if match["result"] == "win" else "你输了"
    events = [f"**{_winner_name(winner)}获胜。**", f"你是【{_role_name(role)}】，{result_text}。"]
    if post_mortem:
        events.extend(post_mortem)

    board_lines = []
    for item in state["players"]:
        if item["seat"] == PLAYER_SEAT:
            label = f"{item['seat']}. 你（{state.get('player_name') or '外乡人'}）"
        else:
            npc = _npc(item["seat"])
            label = f"{item['seat']}. {npc.get('name', '?')}（{npc.get('title', '?')}）"
        status = "存活" if item.get("alive") else "死亡"
        board_lines.append(f"{label} · {status} · {ROLE_ICONS.get(item.get('role'), '')}{_role_name(item.get('role'))}")

    memory_entries = list(matches or []) + [match]
    scene = {
        "title": "🌕 月蚀镇 · 终局",
        "narration": f"月亮彻底暗了下去。{match.get('quote')}",
        "events": events,
        "speeches": [],
        "private": _private_lines(state),
        "board": "\n".join(board_lines),
        "memory": _memory_digest(memory_entries),
        "hint": (
            f"📈 月蚀指数 **{match['eclipse']}/100**　|　"
            f"🗳️ 投票命中 **{int((state.get('stats') or {}).get('correct_votes') or 0)}** 次\n\n"
            "回复 `再来一局` 换一个身份再进月蚀镇；回复 `复盘` 查看本局关键转折。"
        ),
    }
    scene["brief"] = {
        "phase": "ended",
        "day": state.get("day", 1),
        "public_facts": events,
        "speaker_plan": [],
        "memory_digest": _memory_digest(memory_entries),
        "instruction": "写 2-3 句终局氛围，不要改变胜负和身份。",
    }
    return scene


def _restart_confirm_scene(state, matches):
    scene = {
        "title": "🌒 月蚀镇 · 确认重开",
        "narration": "旧的牌局还没结束。你确定要把这一局掀掉吗？",
        "events": ["当前对局会被放弃，PowerContext 里的历史记忆不会消失。"],
        "speeches": [],
        "private": _private_lines(state),
        "board": _board(state),
        "memory": _memory_line(matches),
        "hint": "回复 `重开确认` 放弃本局；回复 `继续` 回到当前对局。",
    }
    scene["brief"] = _default_brief(state, scene, matches)
    return scene


def _current_scene(state, matches):
    phase = state.get("phase")
    if phase == "hunter":
        return _hunter_prompt_scene(state, matches)
    if phase == "night":
        return _night_prompt_scene(state, matches)
    if phase == "day":
        return _day_scene(state, matches, include_dawn=False)
    return _setup_scene(state, matches)


def _recap_scene(matches, state=None):
    if not matches:
        return None
    match = matches[-1]
    lines = [
        f"第 {match.get('no')} 局：你当【{_role_name(match.get('role'))}】，"
        f"{'获胜' if match.get('result') == 'win' else '落败'}。",
        f"月蚀指数：{match.get('eclipse', '?')}/100",
        f"{match.get('highlight', '')}",
    ]
    for event in match.get("post_mortem") or []:
        lines.append(f"- {event}")
    scene = {
        "title": "📜 月蚀镇 · 上一局复盘",
        "narration": "你翻开酒馆柜台下的旧账本，墨迹还没干。",
        "events": lines,
        "speeches": [],
        "private": "",
        "board": _board(state) if state else "",
        "memory": _memory_digest(matches),
        "hint": "回复 `再来一局` 开新局。",
    }
    scene["brief"] = _default_brief(state or {}, scene, matches)
    return scene


def _default_brief(state, scene, matches):
    return {
        "phase": scene.get("title", ""),
        "day": state.get("day", 0),
        "public_facts": scene.get("events") or [],
        "speaker_plan": [],
        "memory_digest": _memory_digest(matches),
        "instruction": "只写氛围，不要改变事实。",
    }


# ---------------------------------------------------------------------------
# 统一响应
# ---------------------------------------------------------------------------


def _compact_state(state):
    raw = _json(state)
    if len(raw.encode("utf-8")) <= MAX_SAVE_BYTES:
        return raw
    state["log"] = list(state.get("log") or [])[-6:]
    state["seer_checks"] = list(state.get("seer_checks") or [])[-4:]
    state["post_mortem"] = list(state.get("post_mortem") or [])[-4:]
    raw = _json(state)
    if len(raw.encode("utf-8")) <= MAX_SAVE_BYTES:
        return raw
    state["post_mortem"] = []
    state["last_vote"] = {}
    state["votes"] = {}
    return _json(state)


def _respond(state, scene, mem, matches):
    state["turn"] = int(state.get("turn") or 0) + 1
    state["updated"] = datetime.now().timestamp()
    scene.setdefault("brief", _default_brief(state, scene, matches))
    scene["brief"]["memory_digest"] = _memory_digest(matches)
    save_text = _compact_state(state)
    payload = {
        "answer_fallback": _scene_markdown(scene),
        "scene_json": _json(scene),
        "brief_json": _json(scene["brief"]),
        "save_text": save_text,
        "save_text_json": json.dumps(save_text, ensure_ascii=False),
        "should_save": True,
        "memory_digest": _memory_digest(matches),
        "phase": str(state.get("phase") or ""),
        "game_id": str(state.get("gid") or ""),
        "turn": int(state.get("turn") or 0),
        "player_role": _role_name(_player_role(state)),
        "debug_json": _json(
            {
                "alive": _alive_seats(state),
                "wolves": _wolves(state),
                "winner": state.get("winner"),
                "save_bytes": len(save_text.encode("utf-8")),
            }
        ),
    }
    return payload


def _setup_response(state, mem):
    matches = mem.get("matches") or []
    scene = _setup_scene(state, matches)
    state["phase"] = "role_select"
    return _respond(state, scene, mem, matches)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def handle_turn(query, scope_id="", recall_body="", player_name="", memory_id=""):
    mem = _parse_memory(recall_body)
    mem["scope_id"] = scope_id
    matches = mem.get("matches") or []
    relations = mem.get("relations") or {}
    state = mem.get("active")
    text = _clean(query, 360)

    if not state:
        if matches and re.search(r"(复盘|回顾|上一局|结局|继续|我回来了)", text):
            scene = _recap_scene(matches, None)
            fake = _new_state(scope_id, player_name, text, matches, relations, "recap")
            fake["status"] = "ended"
            fake["phase"] = "ended"
            fake["match"] = matches[-1]
            return _respond(fake, scene, mem, matches)
        state = _new_state(scope_id, player_name, text, matches, relations)
        role = _parse_role(text)
        if role == "random":
            role = _pick(_sha(scope_id, state.get("gid"), text), ["wolf", "seer", "witch", "hunter", "villager"])
        if role in ROLE_NAMES:
            _assign_roles(state, role, _sha(scope_id, state.get("gid"), role))
            scene = _start_night(state, matches, first=True)
            return _respond(state, scene, mem, matches)
        return _setup_response(state, mem)

    if state.get("status") == "ended":
        if re.search(r"(再来|重开|新局|新一局|开始游戏|继续)", text):
            fresh = _new_state(scope_id, state.get("player_name") or player_name, text, matches, relations, "again")
            return _setup_response(fresh, mem)
        if re.search(r"(复盘|回顾|上一局|结局)", text):
            scene = _recap_scene(matches + ([state.get("match")] if state.get("match") else []), state)
            return _respond(state, scene, mem, matches)
        scene = _finish(state, state.get("winner") or "good", matches)
        return _respond(state, scene, mem, matches)

    phase = state.get("phase")

    if re.search(r"(重开|新游戏|新一局|换个身份|换一局)", text):
        if re.search(r"(确认|确定|开吧|yes)", text):
            fresh = _new_state(scope_id, state.get("player_name") or player_name, text, matches, relations, "restart")
            return _setup_response(fresh, mem)
        return _respond(state, _restart_confirm_scene(state, matches), mem, matches)

    if re.search(r"^(开始游戏|开始|开局)$", text):
        scene = _current_scene(state, matches)
        scene["events"] = ["你已经在月蚀镇里了。"] + list(scene.get("events") or [])
        scene["hint"] = "回复 `继续` 查看当前场面；回复 `重开确认` 放弃本局。\n\n" + (scene.get("hint") or "")
        return _respond(state, scene, mem, matches)

    if phase == "role_select":
        new_name = _extract_name(text)
        if new_name:
            state["player_name"] = new_name
            state["player"]["name"] = new_name
        role = _parse_role(text)
        if role == "random":
            role = _pick(_sha(scope_id, state.get("gid"), text), ["wolf", "seer", "witch", "hunter", "villager"])
        if role not in ROLE_NAMES:
            scene = _role_reprompt_scene(state, text)
            scene["brief"] = _default_brief(state, scene, matches)
            return _respond(state, scene, mem, matches)
        _assign_roles(state, role, _sha(scope_id, state.get("gid"), role))
        scene = _start_night(state, matches, first=True)
        return _respond(state, scene, mem, matches)

    if phase == "night":
        scene = _handle_night(state, text, matches, mem)
        return _respond(state, scene, mem, matches)

    if phase == "day":
        scene = _handle_day(state, text, matches, mem)
        return _respond(state, scene, mem, matches)

    if phase == "hunter":
        if re.search(r"(不开枪|放弃|不带走)", text):
            scene, _finished = _after_deaths(state, matches, [], set(), _sha(state.get("gid"), "hunter-pass"))
            if state.get("status") != "ended" and not _player(state).get("alive"):
                scene = _auto_resolve(state, matches, "你把枪放下了。")
            return _respond(state, scene, mem, matches)
        target = _parse_target(state, text)
        if not target:
            scene = _hunter_prompt_scene(state, matches)
            scene["narration"] = "你要带走谁？回复 `开枪 4`，或者 `不开枪`。"
            return _respond(state, scene, mem, matches)
        _kill(state, target, "猎人开枪")
        state["hunter_shot"] = {"hunter": PLAYER_SEAT, "target": target}
        winner = _check_win(state)
        if winner:
            scene = _finish(state, winner, matches)
        else:
            scene = _auto_resolve(state, matches, f"你开枪带走了 {target} 号，随后倒在了血泊里。")
        return _respond(state, scene, mem, matches)

    state = _new_state(scope_id, player_name, text, matches, relations)
    return _setup_response(state, mem)
