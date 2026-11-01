"""Session close-out: turn one study round into durable memory.

Without an LLM key the extraction is deliberately rule-based and states its
evidence instead of pretending to infer. The three outputs required by the
brief are all real:

* knowledge points - sections actually returned by seekdb in this session;
* error reasons    - the learner's own words from the close-out form;
* new preferences  - phrases in this session's questions plus the optional
                     preference field, matched by explicit rules.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..seekdb import repo
from ..trace.models import LAYER_APP, TraceEvent
from ..trace.models import new_trace_id
from ..memory import service as memory_service
from ..memory.kinds import MemoryKind

_PREFERENCE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"一句话|简短|简洁|别太长|短一点"), "希望回答简洁，先给一句话结论。"),
    (re.compile(r"先.{0,4}结论|结论.{0,4}再"), "偏好先看结论，再看推导过程。"),
    (re.compile(r"例子|举例|实例"), "希望抽象术语都配一个具体例子。"),
    (re.compile(r"推导|证明|为什么"), "希望看到推导过程，而不只是结论。"),
    (re.compile(r"公式|符号|矩阵写法"), "接受并使用公式表达。"),
)


def detect_preferences(texts: list[str]) -> list[dict]:
    joined = "\n".join(text for text in texts if text)
    found: list[dict] = []
    seen: set[str] = set()
    for pattern, preference in _PREFERENCE_RULES:
        if preference in seen:
            continue
        match = pattern.search(joined)
        if match:
            seen.add(preference)
            found.append({"text": preference, "evidence": match.group(0)})
    return found


def _strip_terminal(text: str) -> str:
    return text.strip().rstrip("。？！?!；;，, ")


def _existing_texts(kind: MemoryKind, session_id: str) -> set[str]:
    try:
        rows = memory_service.list_memories(limit=50, session_id=session_id, kinds=[kind])
    except Exception:
        return set()
    return {row["text"].strip() for row in rows}


def _write_once(
    kind: MemoryKind,
    text: str,
    *,
    session_id: str,
    reason: str,
    existing: set[str],
) -> dict | None:
    if text.strip() in existing:
        return None
    entry = memory_service.write_memory(kind, text, session_id=session_id, reason=reason)
    existing.add(text.strip())
    return entry


def close_session(
    session_id: str,
    *,
    topic: str = "",
    struggles: str = "",
    preference: str = "",
) -> dict:
    session = repo.get_session(session_id) or {}
    evidence = repo.session_evidence(session_id)
    resolved_topic = _strip_terminal((topic or session.get("topic") or "").strip())
    if not resolved_topic and evidence["queries"]:
        resolved_topic = evidence["queries"][0]
    resolved_topic = _strip_terminal(resolved_topic)[:80] or "本轮学习"

    sections = evidence["sections"]
    queries = evidence["queries"]
    section_text = "、".join(f"「{section}」" for section in sections[:4]) or "（本轮没有命中资料小节）"
    query_text = "；".join(_strip_terminal(query) for query in queries[:3]) or "（无记录）"
    struggles = _strip_terminal(struggles)
    preference = preference.strip()

    summary_parts = [
        f"{datetime.now().strftime('%Y-%m-%d')} 围绕「{resolved_topic}」完成一轮学习。",
        f"检索覆盖 {section_text}，共 {evidence['searches']} 次 seekdb 检索。",
        f"本轮提出的问题：{query_text}。",
    ]
    if struggles:
        summary_parts.append(f"学习者自述的卡点：{struggles}。")
    else:
        summary_parts.append("本轮没有记录明确的卡点。")
    if sections:
        summary_parts.append(f"下次建议先复习「{sections[0]}」，再做一次回忆式自测。")
    summary_text = "".join(summary_parts)

    written: list[dict] = []
    summary_entry = memory_service.write_memory(
        MemoryKind.SESSION_SUMMARY,
        summary_text,
        session_id=session_id,
        reason="会话收尾自动摘要",
    )
    written.append(summary_entry)

    if struggles:
        weakness_text = (
            f"在「{resolved_topic}」上，学习者自述还没搞清楚：{struggles}。"
            "下次回答先做概念辨析，再给一个具体例子。"
        )
        existing = _existing_texts(MemoryKind.WEAKNESS, session_id)
        entry = _write_once(
            MemoryKind.WEAKNESS,
            weakness_text,
            session_id=session_id,
            reason=f"会话 {session_id} 的自述卡点",
            existing=existing,
        )
        if entry:
            written.append(entry)

    # An explicit preference is authoritative; otherwise keep at most two
    # high-confidence rule matches so a single session cannot flood the profile.
    detected = (
        [{"text": preference, "evidence": "用户手填"}]
        if preference
        else detect_preferences(queries)[:2]
    )
    existing_profiles = _existing_texts(MemoryKind.PROFILE, session_id)
    for item in detected:
        entry = _write_once(
            MemoryKind.PROFILE,
            item["text"],
            session_id=session_id,
            reason=f"会话 {session_id} 的偏好线索：{item['evidence']}",
            existing=existing_profiles,
        )
        if entry:
            written.append(entry)

    repo.end_session(session_id)
    event = TraceEvent(
        session_id=session_id,
        trace_id=new_trace_id(),
        layer=LAYER_APP,
        operation="session_close",
        input_text=resolved_topic,
        result_count=len(written),
        summary=f"收尾写入 {len(written)} 条记忆：" + "、".join(entry["kind"] for entry in written),
        payload={
            "topic": resolved_topic,
            "sections": sections,
            "queries": queries,
            "struggles": struggles,
            "preferences": [item["text"] for item in detected],
            "memory_artifact_ids": [entry.get("artifact_id") for entry in written],
        },
    )
    repo.save_trace(event)

    return {
        "session_id": session_id,
        "topic": resolved_topic,
        "summary": summary_text,
        "evidence": evidence,
        "preferences": [item["text"] for item in detected],
        "memories": written,
        "trace_id": event.trace_id,
        "trace_counts": repo.trace_counts(session_id),
    }
