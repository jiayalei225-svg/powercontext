# -*- coding: utf-8 -*-
"""本地 OpenAI 兼容的「叙事者」服务，用于无模型 Key 时演示/验收。

它不替代真实大模型：只根据 Dify 发来的 speaker_plan 生成模板台词，
保证 JSON 结构、NPC 声线和「记忆回响」可被验证。正式体验建议换成
DeepSeek / Qwen / OpenAI 等真实模型。

运行：
    python tools/openai_shim.py --port 8101
Dify 中配置 OpenAI-API-Compatible：
    Base URL: http://host.docker.internal:8101/v1
    Model:    moonfall-narrator
    API Key:  sk-local-demo
"""

from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 2 * 1024 * 1024


def _find_json(text):
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start : index + 1])
                    return value if isinstance(value, dict) else {}
                except Exception:
                    return {}
    return {}


def _extract_brief(prompt):
    marker = "【场景事实】"
    if marker in prompt:
        return _find_json(prompt.split(marker, 1)[1])
    return _find_json(prompt)


def _first_event(brief):
    events = brief.get("public_facts") or []
    for item in events:
        text = re.sub(r"[*_`#]", "", str(item)).strip()
        if text:
            return text
    return ""


NIGHT_LINES = [
    "第 {day} 夜的月亮像一枚生锈的硬币。风从门缝里钻进来，吹得烛火东倒西歪。有人翻了个身，也有人一直没有睡。",
    "钟楼敲了十二下，最后一下没有回音。第 {day} 夜的月蚀镇，连老鼠都闭了嘴。",
    "窗外的雾贴着玻璃，像一张没有五官的脸。第 {day} 夜，谁也没有吹灭蜡烛。",
]

DAY_LINES = [
    "天亮了。{event}酒馆里没人先开口，只有钟表匠的怀表在走。",
    "晨光从百叶窗缝里挤进来，照出桌上几道没有擦干净的血印。{event}",
    "面包烤糊了，没人去管。{event}所有人都在等第一个开口的人。",
]


def _narration(brief):
    phase = str(brief.get("phase") or "")
    day = brief.get("day") or 1
    event = _first_event(brief)
    seed = sum(ord(char) for char in str(brief.get("turn")) + ":" + phase + ":" + str(day))
    if "night" in phase:
        return NIGHT_LINES[seed % len(NIGHT_LINES)].format(day=day)
    if "vote" in phase:
        return f"红姨把空酒杯放在桌子中央。{event}没人先动，仿佛先动的人就会先被写进账单。"
    if "hunter" in phase:
        return "血滴在地板上，声音比钟摆还慢。猎枪的枪口抬起来，所有人同时屏住了呼吸。"
    if "ended" in phase:
        return f"月亮彻底暗了下去。{event}月蚀镇不记仇，它只记账。"
    if "role_select" in phase:
        return "门外的风停了。八张身份牌在桌上排成一圈，像八口没有盖子的井。"
    if event:
        text = DAY_LINES[seed % len(DAY_LINES)].format(event=event.rstrip("。") + "。")
        return text
    return "天亮了。酒馆里没人先开口，只有钟表匠的怀表在走。"


SPEECHES = {
    2: [
        "我抡铁锤的，不讲虚的。{target} 号，你昨晚到底在哪儿？",
        "别绕弯子。{target} 号，你刚才那句话前后对不上。",
        "我这人脾气直。{target} 号，你要是不解释，我这票就给你了。",
    ],
    3: [
        "愿月神宽恕你——不过 {target} 号，你的手从刚才起就在抖。",
        "{target} 号，我不是在审判你，我只是在记账。",
        "主说不要妄断，可 {target} 号，你今天的沉默太吵了。",
    ],
    4: [
        "我跟你们说，这事儿不对劲。{target} 号，你昨天可不是这么说的。",
        "{target} 号，你别看我，我、我只是个送信的，但我什么都听见了。",
        "我重复一遍，{target} 号说“我没出门”，可雪地上有他的脚印。",
    ],
    5: [
        "在我店里，命也是要付账的。{target} 号，你拿什么付？",
        "{target} 号，你昨晚那杯酒一口没动。是不敢喝，还是怕睡着？",
        "我做买卖讲究现结。{target} 号，你的解释最好也现结。",
    ],
    6: [
        "皮皮看见啦，{target} 号半夜在数楼梯。一、二、三……少了一级。",
        "{target} 号说自己是好人，皮皮就笑了。好人可不会把影子落在门外。",
        "月亮缺一角，{target} 号少一句真话。皮皮给他们配个对。",
    ],
    7: [
        "时间会证明一切，通常证明我是对的。{target} 号，你迟到了三分钟。",
        "我记录过 {target} 号昨晚的灯：子时亮，丑时灭。中间那一个小时，够做很多事。",
        "{target} 号，你的解释比我的钟还慢。",
    ],
    8: [
        "我、我烤了面包……{target} 号，你要不要先吃一口？吃了就、就说真话吧。",
        "{target} 号，我胆子小，可我看得很清楚。你昨晚没有回房间。",
        "我、我不想投错人……但是 {target} 号，你的鞋底有井边的泥。",
    ],
}


def _speech(item, brief):
    seat = int(item.get("seat") or 0)
    if seat not in SPEECHES:
        return ""
    target = item.get("target")
    if not target:
        target = "那边"
    seed = sum(
        ord(char)
        for char in str(brief.get("day")) + ":" + str(seat) + ":" + str(brief.get("phase")) + ":" + str(brief.get("turn"))
    )
    text = SPEECHES[seat][seed % len(SPEECHES[seat])]
    text = text.format(target=target)
    memory = str(brief.get("memory_digest") or "")
    if seat == 2 and "第 1 局" in memory and "信任 -" in memory:
        text = "又是你。上次你也这么看着我，结果我是好人。 " + text
    return text[:140]


def make_payload(prompt):
    brief = _extract_brief(prompt)
    plan = brief.get("speaker_plan") or []
    speeches = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        text = _speech(item, brief)
        if text:
            speeches.append({"seat": int(item.get("seat")), "text": text})
    payload = {"narration": _narration(brief), "speeches": speeches}
    return json.dumps(payload, ensure_ascii=False)


def _last_user(messages):
    for item in reversed(messages or []):
        if isinstance(item, dict) and item.get("role") == "user":
            return str(item.get("content") or "")
    return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "MoonfallShim/1.0"

    def _send(self, status, payload, content_type="application/json"):
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/healthz"):
            self._send(200, {"ok": True, "model": "moonfall-narrator"})
            return
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "moonfall-narrator", "object": "model", "created": int(time.time()), "owned_by": "moonfall"}
                    ],
                },
            )
            return
        self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                raise ValueError("bad length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            self._send(400, {"error": {"message": str(exc)}})
            return

        prompt = _last_user(payload.get("messages"))
        content = make_payload(prompt)
        model = str(payload.get("model") or "moonfall-narrator")
        created = int(time.time())
        if payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            for chunk in (content[: max(1, len(content) // 2)], content[max(1, len(content) // 2) :]):
                event = {
                    "id": "chatcmpl-moonfall",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            final = {
                "id": "chatcmpl-moonfall",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self._send(
            200,
            {
                "id": "chatcmpl-moonfall",
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": len(prompt) // 3, "completion_tokens": len(content) // 3, "total_tokens": 0},
            },
        )

    def log_message(self, fmt, *args):
        print(f"[shim] {self.address_string()} {fmt % args}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="月蚀镇本地叙事者 shim")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8101)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Moonfall narrator shim -> http://{args.host}:{args.port}/v1 (model=moonfall-narrator)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
