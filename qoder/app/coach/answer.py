"""Answer composition.

Two modes, both honest:

* ``llm``      - an OpenAI-compatible endpoint is configured and answers from
                 the retrieved evidence with the memory block as personalisation.
* ``evidence`` - no endpoint configured. The answer is assembled from the
                 retrieved chunks and the recalled memories without inventing
                 anything, and the UI labels it as evidence-only.

Neither mode answers when retrieval is empty; the response says so.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import settings
from ..seekdb import repo
from ..trace.models import LAYER_LLM, TraceEvent

_SENTENCE = re.compile(r"(?<=[。！？；!?;])")
HIGHLIGHT_KINDS = ("weakness", "session_summary")


_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s*")


def _clean_chunk(text: str) -> str:
    lines = [line for line in text.splitlines() if not _HEADING_LINE.match(line)]
    return " ".join(line.strip() for line in lines if line.strip())


def _first_sentences(text: str, count: int = 2, limit: int = 220) -> str:
    cleaned = _clean_chunk(text)
    parts = [part.strip() for part in _SENTENCE.split(cleaned) if part.strip()]
    joined = "".join(parts[:count]) or cleaned
    return joined[:limit] + ("…" if len(joined) > limit else "")


def _highlight(memories: list[dict]) -> dict | None:
    for kind in HIGHLIGHT_KINDS:
        for memory in memories:
            if memory.get("kind") == kind and memory.get("text"):
                return memory
    return None


def evidence_answer(question: str, results: list[dict], memories: list[dict]) -> str:
    lines: list[str] = []
    highlight = _highlight(memories)
    if highlight is not None:
        lines.append(f"先说一句我记住的情况：{highlight['text']}")
    if not results:
        lines.append("资料库里没有检索到直接相关的内容。可以换一个更具体的说法，或先在「资料库」导入相关讲义。")
        return "\n\n".join(lines)

    lines.append("根据资料：")
    for index, hit in enumerate(results[:2], start=1):
        lines.append(
            f"{index}. 〔{hit['doc_title']} · {hit['section']}〕"
            f"{_first_sentences(hit['text'])} [{index}]"
        )
    if len(results) > 2:
        lines.append(f"另外还找到 {len(results) - 2} 条相关片段，列在下方引用里。")
    if highlight is not None and highlight["kind"] == "weakness":
        lines.append(f"下一步建议：先回看「{results[0]['section']}」，再针对上次的错因做一道辨析题，确认这次没有记反。")
    else:
        lines.append(f"下一步建议：用「{results[0]['section']}」里的定义复述一遍，再进入「今日复习」做一次自测。")
    return "\n\n".join(lines)


def _llm_messages(question: str, results: list[dict], memory_block: str) -> list[dict]:
    system = (
        "你是 StudyCoach，一位克制、准确的中文学习教练。"
        "只能依据用户给的教材证据回答；证据不足时直接说明，不要补充常识或编造。"
        "引用证据时使用方括号编号，例如 [1]。"
        "记忆块只用于个性化提醒，不是教材证据，也不要逐条复述。"
        "回答控制在三段以内，先给结论，再给依据。"
    )
    evidence_lines = []
    for index, hit in enumerate(results[:5], start=1):
        evidence_lines.append(
            f"[{index}] 《{hit['doc_title']}》 {hit['section']}（第 {hit['page']} 页）\n{hit['text']}"
        )
    user = "\n\n".join(
        part
        for part in (
            memory_block,
            "教材证据：\n" + ("\n\n".join(evidence_lines) or "（无）"),
            f"学习者的问题：{question}",
        )
        if part
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def llm_answer(
    question: str,
    results: list[dict],
    memory_block: str,
    *,
    session_id: str,
) -> tuple[str | None, dict[str, Any]]:
    """Call the optional OpenAI-compatible chat endpoint. Returns (answer, meta)."""
    if not (settings.llm_base_url and settings.llm_model):
        return None, {"configured": False}
    payload = {
        "model": settings.llm_model,
        "messages": _llm_messages(question, results, memory_block),
        "temperature": 0.2,
    }
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as error:  # surfaced in the trace and the response meta
        event = TraceEvent(
            session_id=session_id,
            layer=LAYER_LLM,
            operation="chat",
            input_text=question,
            result_count=0,
            summary=f"LLM 调用失败：{type(error).__name__}: {error}"[:300],
            payload={"model": settings.llm_model, "base_url": settings.llm_base_url},
        )
        repo.save_trace(event)
        return None, {"configured": True, "error": str(error), "trace_id": event.trace_id}
    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_LLM,
        operation="chat",
        input_text=question,
        result_count=1,
        summary=f"LLM {settings.llm_model} 返回 {len(content)} 字",
        payload={"model": settings.llm_model, "answer_preview": content[:160]},
    )
    repo.save_trace(event)
    return content, {"configured": True, "trace_id": event.trace_id}
