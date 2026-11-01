"""Evidence-grounded practice: generate questions from chunks, score answers.

No question is authored by hand and no answer is model-generated. Every item is
built from a chunk that is already indexed in seekdb, and its answer is the
section label or the source excerpt itself. That keeps the quiz verifiable: the
explanation always points back to ``source_chunk_id``.

Scoring writes two kinds of state:

* seekdb  - practice record, mastery score, SM-2 interval, review timestamp;
* PowerContext - the error reason and the day's task progress, so the next
  question-answer session can recall where the learner struggled.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..memory import service as memory_service
from ..memory.kinds import MemoryKind
from ..seekdb import db, repo
from ..trace.models import LAYER_SEEKDB, TraceEvent
from . import mastery

_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s*")
_TERM_PREFIX = re.compile(r"^\d+(?:\.\d+)*\s*")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(text: str) -> str:
    lines = [line for line in (text or "").splitlines() if not _HEADING_LINE.match(line)]
    return " ".join(line.strip() for line in lines if line.strip())


def _snippet(text: str, limit: int = 130) -> str:
    clean = _clean(text)
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("！"), cut.rfind("？"))
    if boundary >= int(limit * 0.55):
        cut = cut[: boundary + 1]
    return cut.rstrip() + "…"


def _short(text: str, limit: int = 60) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[:limit] + "…"


def _question_id(kind: str, kp_id: str, chunk_id: str) -> str:
    digest = hashlib.sha1(f"{kind}|{kp_id}|{chunk_id}".encode("utf-8")).hexdigest()
    return f"q-{digest[:16]}"


def _chunk_texts(chunk_ids: list[str]) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    result = db.collection().get(
        ids=chunk_ids,
        include=["documents", "metadatas"],
    )
    out: dict[str, dict] = {}
    for chunk_id, text, metadata in zip(
        result.get("ids") or [],
        result.get("documents") or [],
        result.get("metadatas") or [],
    ):
        out[chunk_id] = {
            "text": text or "",
            "doc_title": (metadata or {}).get("doc_title") or "",
            "section": (metadata or {}).get("section") or "",
            "chunk_id": chunk_id,
        }
    return out


def _source_for(kp_id: str, chunks: dict[str, list[str]], texts: dict[str, dict]) -> dict | None:
    for chunk_id in chunks.get(kp_id, []):
        source = texts.get(chunk_id)
        if source and _snippet(source["text"]):
            return {**source, "chunk_id": chunk_id}
    return None


def _distractors(kp: dict, catalog: list[dict], seed: str, count: int = 3) -> list[dict]:
    others = [item for item in catalog if item["kp_id"] != kp["kp_id"] and item["name"] != kp["name"]]
    others.sort(key=lambda item: (item["subject"] != kp["subject"], item["name"]))
    rng = random.Random(seed)
    if len(others) > count:
        same = [item for item in others if item["subject"] == kp["subject"]]
        rest = [item for item in others if item["subject"] != kp["subject"]]
        if len(same) >= count:
            picked = same[:]
            rng.shuffle(picked)
            return picked[:count]
        rest_pick = rest[: count - len(same)]
        return same + rest_pick
    return others[:count]


def _build(
    kp: dict,
    catalog: list[dict],
    kind: str,
    chunks: dict[str, list[str]],
    texts: dict[str, dict],
) -> dict | None:
    source = _source_for(kp["kp_id"], chunks, texts)
    if not source:
        return None
    correct_snippet = _snippet(source["text"])
    if not correct_snippet:
        return None
    question_id = _question_id(kind, kp["kp_id"], source["chunk_id"])
    distractors = _distractors(kp, catalog, question_id)

    if kind == "excerpt_to_kp":
        options = [kp["name"]] + [item["name"] for item in distractors]
        answer = kp["name"]
        prompt = (
            "下面这段原文出自哪个知识点？\n\n"
            f"「{correct_snippet}」"
        )
        explanation = (
            f"原文出自《{source['doc_title']}》的「{source['section']}」，"
            f"对应知识点「{kp['name']}」。引用 chunk {source['chunk_id']}。"
        )
    else:
        distractor_snippets: list[str] = []
        for item in distractors:
            other = _source_for(item["kp_id"], chunks, texts)
            snippet = _snippet(other["text"]) if other else ""
            if snippet and snippet != correct_snippet and snippet not in distractor_snippets:
                distractor_snippets.append(snippet)
        if len(distractor_snippets) < 2:
            return None
        options = [correct_snippet] + distractor_snippets
        answer = correct_snippet
        prompt = f"下面哪一段原文最可能讲「{kp['name']}」？"
        explanation = (
            f"正确段落出自《{source['doc_title']}》的「{source['section']}」。"
            f"其余段落来自其他小节。引用 chunk {source['chunk_id']}。"
        )

    if len(options) < 2:
        return None
    rng = random.Random(question_id)
    rng.shuffle(options)
    return {
        "question_id": question_id,
        "kp_id": kp["kp_id"],
        "kp_name": kp["name"],
        "subject": kp["subject"],
        "question_type": kind,
        "prompt": prompt,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "source_chunk_id": source["chunk_id"],
    }


def generate(
    *,
    limit: int = 5,
    subject: str | None = None,
    session_id: str = "quiz",
) -> dict:
    catalog = repo.list_knowledge_points(subject)
    if not catalog:
        raise ValueError("还没有可练习的知识点，请先在资料库导入 md / txt / pdf")

    due_ids = {row["kp_id"] for row in repo.review_queue(subject, limit=200)}
    new_ids = {item["kp_id"] for item in catalog if item.get("score") is None}
    ordered = [item for item in catalog if item["kp_id"] in due_ids]
    ordered += [item for item in catalog if item["kp_id"] not in due_ids]
    selected = ordered[:limit]

    chunk_map = repo.chunk_ids_for_kps([item["kp_id"] for item in catalog])
    first_chunks = [ids[0] for ids in chunk_map.values() if ids]
    texts = _chunk_texts(first_chunks)

    built: list[dict] = []
    seen: set[str] = set()
    for index, kp in enumerate(selected):
        preferred = "excerpt_to_kp" if index % 2 == 0 else "kp_to_excerpt"
        for kind in (preferred, "kp_to_excerpt" if preferred == "excerpt_to_kp" else "excerpt_to_kp"):
            question = _build(kp, catalog, kind, chunk_map, texts)
            if question and question["question_id"] not in seen:
                built.append(question)
                seen.add(question["question_id"])
                break

    if len(built) < limit and len(catalog) > 0:
        # A small library may not have enough distinct sections; generate the
        # second question type for the same points rather than inventing items.
        for kp in ordered:
            if len(built) >= limit:
                break
            for kind in ("excerpt_to_kp", "kp_to_excerpt"):
                question = _build(kp, catalog, kind, chunk_map, texts)
                if question and question["question_id"] not in seen:
                    built.append(question)
                    seen.add(question["question_id"])
                    break

    for item in built:
        repo.upsert_question(
            {
                **item,
                "prompt_text": item["prompt"],
                "options_json": json.dumps(item["options"], ensure_ascii=False),
            }
        )

    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation="quiz_generate",
        input_text=f"limit={limit} subject={subject or '全部'}",
        result_count=len(built),
        summary=f"从 seekdb 原文生成 {len(built)} 道题（{len(selected)} 个知识点）",
        payload={
            "question_ids": [item["question_id"] for item in built],
            "kp_ids": [item["kp_id"] for item in built],
            "types": [item["question_type"] for item in built],
            "due_points": len(due_ids),
        },
    )
    repo.save_trace(event)

    return {
        "questions": [
            {
                "question_id": item["question_id"],
                "kp_id": item["kp_id"],
                "kp_name": item["kp_name"],
                "subject": item["subject"],
                "question_type": item["question_type"],
                "prompt": item["prompt"],
                "options": item["options"],
            }
            for item in built
        ],
        "count": len(built),
        "selection": {
            "queue": len([item for item in built if item["kp_id"] in due_ids]),
            "new": len([item for item in built if item["kp_id"] in new_ids]),
            "knowledge_points": len(catalog),
        },
        "trace_id": event.trace_id,
    }


def _write_quiz_memories(results: list[dict], note: str, session_id: str) -> tuple[list[dict], list[str]]:
    memories: list[dict] = []
    errors: list[str] = []
    total = len(results)
    correct_count = sum(1 for item in results if item["correct"])
    wrong = [item for item in results if not item["correct"]]
    weak_names = [item["kp_name"] for item in wrong]

    task_text = f"{_now().strftime('%Y-%m-%d')} 完成 {total} 道练习：正确 {correct_count} 道。"
    if weak_names:
        task_text += "需要回看：" + "、".join(list(dict.fromkeys(weak_names))[:4]) + "。"
    try:
        memories.append(
            memory_service.write_memory(
                MemoryKind.TASK_STATE,
                task_text,
                session_id=session_id,
                reason="练习提交后的今日进展",
            )
        )
    except Exception as error:
        errors.append(f"task_state: {type(error).__name__}: {error}")

    for item in wrong[:3]:
        text = (
            f"在「{item['kp_name']}」的练习中答错：我选了「{_short(item['chosen'], 44)}」，"
            f"正确答案是「{_short(item['answer'], 44)}」。下次先做概念辨析。"
        )
        try:
            memories.append(
                memory_service.write_memory(
                    MemoryKind.WEAKNESS,
                    text,
                    session_id=session_id,
                    reason=f"练习 {item['question_id']} 答错",
                )
            )
        except Exception as error:
            errors.append(f"weakness: {type(error).__name__}: {error}")

    if note.strip():
        try:
            memories.append(
                memory_service.write_memory(
                    MemoryKind.WEAKNESS,
                    f"本轮练习的错因自述：{note.strip()[:300]}",
                    session_id=session_id,
                    reason="用户在练习提交时填写的错因",
                )
            )
        except Exception as error:
            errors.append(f"note: {type(error).__name__}: {error}")

    return memories, errors


def submit(
    answers: list[dict],
    *,
    session_id: str = "quiz",
    note: str = "",
) -> dict:
    unique: dict[str, dict] = {}
    for answer in answers:
        question_id = str(answer.get("question_id") or "").strip()
        if question_id and question_id not in unique:
            unique[question_id] = answer
    if not unique:
        raise ValueError("至少提交一道题的答案")

    questions = repo.questions_by_ids(list(unique))
    missing = [question_id for question_id in unique if question_id not in questions]
    if missing:
        raise ValueError(f"题目不存在：{', '.join(missing[:3])}")

    now = _now()
    results: list[dict] = []
    answer_rows: list[dict] = []
    for question_id, answer in unique.items():
        question = questions[question_id]
        chosen = str(answer.get("chosen") or "").strip()
        correct = chosen == str(question["answer"] or "").strip()
        before = repo.get_mastery(question["kp_id"])
        after = mastery.update(before, correct, now=now)
        after["kp_id"] = question["kp_id"]
        repo.upsert_mastery(after)
        repo.insert_practice_record(
            {
                "record_id": f"pr-{uuid4().hex[:16]}",
                "session_id": session_id,
                "kp_id": question["kp_id"],
                "question_id": question_id,
                "is_correct": correct,
                "answer_text": chosen,
                "created_at": now,
            }
        )
        result = {
            "question_id": question_id,
            "kp_id": question["kp_id"],
            "kp_name": question.get("kp_name") or question["kp_id"],
            "question_type": question["question_type"],
            "prompt": question["prompt_text"],
            "chosen": chosen,
            "answer": question["answer"],
            "correct": correct,
            "explanation": question.get("explanation") or "",
            "source_chunk_id": question.get("source_chunk_id"),
            "mastery_before": round(float(before["score"]), 4) if before else 0.5,
            "mastery_after": after["score"],
            "next_review_at": repo.iso(after["next_review_at"]),
            "next_review_label": mastery.describe_next(after["next_review_at"], now=now),
            "interval_days": after["interval_days"],
        }
        results.append(result)
        answer_rows.append(
            {
                "question_id": question_id,
                "kp_id": question["kp_id"],
                "correct": correct,
                "chosen": chosen[:120],
                "mastery_before": result["mastery_before"],
                "mastery_after": result["mastery_after"],
                "next_review_at": result["next_review_at"],
            }
        )

    correct_count = sum(1 for item in results if item["correct"])
    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation="quiz_submit",
        input_text=f"{len(results)} answers",
        result_count=correct_count,
        summary=f"提交 {len(results)} 题：正确 {correct_count} 题",
        payload={"answers": answer_rows},
    )
    repo.save_trace(event)

    memories, errors = _write_quiz_memories(results, note, session_id)
    return {
        "session_id": session_id,
        "score": {
            "correct": correct_count,
            "total": len(results),
            "accuracy": round(correct_count / len(results), 4) if results else 0,
        },
        "results": results,
        "memories": memories,
        "memory_error": "；".join(errors) if errors else None,
        "trace_id": event.trace_id,
    }
