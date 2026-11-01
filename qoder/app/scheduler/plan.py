"""Turn the live review queue into a short, dated study plan.

The plan is written to PowerContext as a ``plan`` memory so a later Q&A can
recall what the learner intended to do, not just what they got wrong.
"""

from __future__ import annotations

from ..memory import service as memory_service
from ..memory.kinds import MemoryKind
from ..seekdb import repo
from ..trace.models import LAYER_SEEKDB, TraceEvent


def build(*, days: int = 3, limit: int = 5, session_id: str = "plan") -> dict:
    rows = repo.review_queue(limit=limit)
    if not rows:
        raise ValueError("当前没有可排入计划的知识点，请先导入资料或提交一次练习")
    stats = repo.review_stats()

    parts: list[str] = []
    for row in rows:
        score = row.get("score")
        state = "未练习" if score is None else f"掌握度 {round(float(score) * 100)}%"
        parts.append(f"「{row['name']}」（{row['subject']}，{state}）")
    text = (
        f"未来 {days} 天的学习计划：先复习 " + "、".join(parts) +
        f"。每天约 20 分钟，先看原文再做自测；当前待复习 {stats['due']} 个知识点，"
        "完成后到「今日复习」提交练习，掌握度和下次复习时间会自动更新。"
    )

    entry = None
    reused = False
    for row in memory_service.list_memories(limit=50, session_id=session_id, kinds=[MemoryKind.PLAN]):
        if row["text"].strip() == text:
            entry = row
            reused = True
            break
    if entry is None:
        entry = memory_service.write_memory(
            MemoryKind.PLAN,
            text,
            session_id=session_id,
            reason="根据今日复习队列生成的学习计划",
        )

    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation="build_plan",
        input_text=f"days={days} limit={limit}",
        result_count=len(rows),
        summary=(
            f"复用已有 {days} 天计划（{len(rows)} 个知识点）" if reused
            else f"按复习队列生成 {days} 天计划（{len(rows)} 个知识点）"
        ),
        payload={
            "stats": stats,
            "kp_ids": [row["kp_id"] for row in rows],
            "memory_artifact_id": entry.get("artifact_id"),
            "reused": reused,
        },
    )
    repo.save_trace(event)
    return {
        "plan": text,
        "days": days,
        "queue": [
            {"kp_id": row["kp_id"], "name": row["name"], "subject": row["subject"], "score": row.get("score")}
            for row in rows
        ],
        "memories": [entry],
        "reused": reused,
        "trace_id": event.trace_id,
    }
