"""Memory kinds shared by the memory writer, the prompt builder and the UI.

PowerContext stores an arbitrary ``kind`` string next to each memory and returns
it on search, so kind filtering happens after recall in the application layer.
The stored text stays plain natural language; the kind is never duplicated
inside the text, which keeps embeddings and the prompt readable.
"""

from __future__ import annotations

from enum import Enum


class MemoryKind(str, Enum):
    PROFILE = "profile"
    WEAKNESS = "weakness"
    SESSION_SUMMARY = "session_summary"
    PLAN = "plan"
    TASK_STATE = "task_state"


KIND_LABELS: dict[MemoryKind, str] = {
    MemoryKind.PROFILE: "学习偏好",
    MemoryKind.WEAKNESS: "薄弱点与错因",
    MemoryKind.SESSION_SUMMARY: "会话摘要",
    MemoryKind.PLAN: "学习计划",
    MemoryKind.TASK_STATE: "任务进展",
}

KIND_DESCRIPTIONS: dict[MemoryKind, str] = {
    MemoryKind.PROFILE: "跨会话稳定的偏好，例如讲解顺序、一次推送几个知识点。",
    MemoryKind.WEAKNESS: "具体知识点上的错因归因，用于下次出题和回答时主动提醒。",
    MemoryKind.SESSION_SUMMARY: "一轮会话涉及的知识点、卡点与下次建议。",
    MemoryKind.PLAN: "用户确认过的复习节奏与优先级。",
    MemoryKind.TASK_STATE: "资料导入、今日完成度等可变化的任务进展。",
}


def normalize_kind(value: str) -> MemoryKind:
    try:
        return MemoryKind(str(value))
    except ValueError as error:
        allowed = ", ".join(kind.value for kind in MemoryKind)
        raise ValueError(f"unknown memory kind '{value}', expected one of: {allowed}") from error
