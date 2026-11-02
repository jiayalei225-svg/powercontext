# -*- coding: utf-8 -*-
"""把叙事者 LLM 的输出合并回游戏引擎生成的场景。

Dify 的 LLM 节点只负责「氛围与台词」，所有事实（死亡、投票、身份、胜负）
都来自 engine 的 scene_json。即使模型输出不合格，这个节点也会用引擎生成的
兜底文本完整回答，所以应用不会因为模型抽风而卡死。
"""

import json
import re

MAX_NARRATION = 260
MAX_SPEECH = 140


def _load(raw, fallback):
    try:
        value = json.loads(raw or "")
        return value if isinstance(value, dict) else fallback
    except Exception:
        return fallback


def _strip_fence(text):
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _find_object(text):
    value = _strip_fence(text)
    start = value.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(value)):
        char = value[index]
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
                candidate = value[start : index + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return None
    return None


def _clean(text, limit):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit]


def _merge(scene, llm):
    merged = dict(scene or {})
    if not isinstance(llm, dict):
        return merged, False

    narration = _clean(llm.get("narration"), MAX_NARRATION)
    if narration:
        merged["narration"] = narration

    plan_items = scene.get("speaker_plan") or (scene.get("brief") or {}).get("speaker_plan") or []
    plan = {int(item.get("seat")): item for item in plan_items if item.get("seat")}
    fallback = {int(item.get("seat")): item for item in (scene.get("speeches") or []) if item.get("seat")}
    used = False
    speeches = []
    raw_speeches = llm.get("speeches")
    if not isinstance(raw_speeches, list):
        raw_speeches = []
    for item in raw_speeches:
        if not isinstance(item, dict):
            continue
        try:
            seat = int(item.get("seat"))
        except Exception:
            continue
        text = _clean(item.get("text"), MAX_SPEECH)
        if not text or seat not in plan:
            continue
        name = plan[seat].get("name") or fallback.get(seat, {}).get("name") or f"{seat}号"
        speeches.append({"seat": seat, "name": name, "text": text})
        used = True
    for seat, item in fallback.items():
        if not any(speech["seat"] == seat for speech in speeches):
            speeches.append(item)
    speeches.sort(key=lambda item: item["seat"])
    if speeches:
        merged["speeches"] = speeches
    merged["llm_used"] = used or bool(narration)
    return merged, merged["llm_used"]


def _markdown(scene):
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


def main(scene_json, llm_text, save_text, save_text_json, should_save):
    scene = _load(scene_json, {})
    parsed = _find_object(llm_text) or _strip_fence(llm_text)
    merged, used = _merge(scene, parsed)
    if not scene:
        answer = _clean(llm_text, 1200) or "月蚀镇的雾太浓了，什么也看不清。请再试一次。"
    else:
        answer = _markdown(merged)
    return {
        "answer": answer,
        "save_text": save_text or "",
        "save_text_json": save_text_json or json.dumps(save_text or "", ensure_ascii=False),
        "should_save": bool(should_save),
        "llm_used": bool(used),
    }
