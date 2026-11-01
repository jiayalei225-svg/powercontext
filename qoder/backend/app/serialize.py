"""Export helpers for saving a recall run outside the app."""

from __future__ import annotations

import csv
import io
from datetime import datetime

def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _filter_line(filters: dict) -> str:
    parts = []
    if filters.get("year_from"):
        parts.append(f"≥ {filters['year_from']}")
    if filters.get("year_to"):
        parts.append(f"≤ {filters['year_to']}")
    if filters.get("venues"):
        parts.append("、".join(filters["venues"]))
    if filters.get("field"):
        parts.append(filters["field"])
    if filters.get("has_code"):
        parts.append("仅开源")
    return " / ".join(parts) if parts else "无"


def markdown(payload: dict) -> str:
    lines = [
        "# PaperDesk 检索报告",
        "",
        f"- 检索式：{payload['query']}",
        f"- 生成时间：{_stamp()}",
        f"- 命中片段：{payload['total']} 条（{payload['strategy']} 召回）",
        f"- 词法锚点：{payload.get('literal') or '无'}",
        f"- 过滤条件：{_filter_line(payload.get('filters') or {})}",
        f"- 记忆默认：{'；'.join(payload.get('notes') or []) or '未应用'}",
        "",
        "| # | 论文 | 年份 | 会议/期刊 | 页码 | 开源 |",
        "| - | ---- | ---- | --------- | ---- | ---- |",
    ]
    for position, hit in enumerate(payload["results"], start=1):
        title = (hit.get("title") or "").replace("|", "／")
        lines.append(
            f"| {position} | {title} | {hit.get('year') or '-'} | {hit.get('venue') or '-'} "
            f"| {hit.get('page') or '-'} | {'是' if hit.get('has_code') else '否'} |"
        )
    lines.append("")
    for position, hit in enumerate(payload["results"], start=1):
        lines.append(f"## {position}. {hit.get('title')}")
        lines.append("")
        lines.append(
            f"*{hit.get('venue') or '未标注'} · {hit.get('year') or '年份未知'} · 第 {hit.get('page')} 页 · "
            f"`{hit.get('paper_id')}`*"
        )
        if hit.get("code_url"):
            lines.append(f"\n代码：{hit['code_url']}")
        lines.append("")
        lines.append(hit.get("snippet") or hit.get("text") or "")
        lines.append("")
    return "\n".join(lines)


def csv_text(payload: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["序号", "标题", "年份", "会议/期刊", "方向", "页码", "是否有代码", "代码链接", "片段"])
    for position, hit in enumerate(payload["results"], start=1):
        writer.writerow(
            [
                position,
                hit.get("title") or "",
                hit.get("year") or "",
                hit.get("venue") or "",
                hit.get("field") or "",
                hit.get("page") or "",
                "是" if hit.get("has_code") else "否",
                hit.get("code_url") or "",
                hit.get("snippet") or "",
            ]
        )
    writer.writerow([])
    writer.writerow(["检索式", payload["query"]])
    writer.writerow(["过滤条件", _filter_line(payload.get("filters") or {})])
    writer.writerow(["生成时间", _stamp()])
    return "\ufeff" + buffer.getvalue()
