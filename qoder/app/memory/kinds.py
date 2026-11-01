"""PowerContext memory kinds and the text envelope used around them.

PowerContext stores free text with an arbitrary ``kind`` string, but its search
API has no kind filter (only ``tag_filter``). To keep kind-aware recall honest,
every memory written by this app starts with a one-line header:

    [kind=weakness][subject=机器学习][topic=正则化][at=2026-10-30T21:04:00+08:00]
    把 L1 与 L2 的稀疏性记反了，连续两次在同一个辨析题上出错。

The header is machine-readable, the rest stays natural language, and the UI can
show both. Recall fetches a wider semantic result and filters by kind locally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
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

_HEADER_PAIR = re.compile(r"\[([a-z_]+)=([^\]]*)\]")
_HEADER_PREFIX = re.compile(r"^(?:\[[a-z_]+=[^\]]*\])+\s*")


@dataclass(frozen=True)
class MemoryRecord:
    kind: MemoryKind | None
    text: str
    subject: str = ""
    topic: str = ""
    at: str = ""
    raw: str = ""


def build_memory_text(
    kind: MemoryKind,
    text: str,
    *,
    subject: str = "",
    topic: str = "",
    at: datetime | None = None,
) -> str:
    stamp = (at or datetime.now().astimezone()).isoformat(timespec="seconds")
    header = f"[kind={kind.value}][subject={subject}][topic={topic}][at={stamp}]"
    return f"{header}\n{text.strip()}"


def parse_memory_text(raw: str) -> MemoryRecord:
    first_line, _, body = raw.partition("\n")
    pairs = dict(_HEADER_PAIR.findall(first_line)) if first_line.startswith("[") else {}
    kind_value = pairs.get("kind", "")
    try:
        kind = MemoryKind(kind_value)
    except ValueError:
        kind = None
    text = body.strip() if pairs else _HEADER_PREFIX.sub("", raw).strip()
    return MemoryRecord(
        kind=kind,
        text=text,
        subject=pairs.get("subject", ""),
        topic=pairs.get("topic", ""),
        at=pairs.get("at", ""),
        raw=raw,
    )
