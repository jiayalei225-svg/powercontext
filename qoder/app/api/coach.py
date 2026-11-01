"""Coaching endpoints: ask, close a session, inspect memory.

``/api/ask`` is the only place where the two storage systems meet in one
request. Order matters and is visible in the trace panel:

1. seekdb hybrid retrieval (knowledge, citations);
2. PowerContext recall + context build (personalisation);
3. optional LLM or evidence-only composition;
4. one ``answer`` trace tying both trace families together.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..coach import answer as answerer
from ..coach import session as session_coach
from ..config import settings
from ..memory import service as memory_service
from ..memory.client import PowerContextError
from ..retrieval import hybrid
from ..seekdb import repo
from ..trace.models import LAYER_APP, TraceEvent

router = APIRouter(prefix="/api", tags=["coach"])

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str = "chat"
    mode: str = "hybrid"
    subject: str | None = None
    doc_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=10)


class CloseRequest(BaseModel):
    session_id: str
    topic: str = ""
    struggles: str = Field(default="", max_length=1000)
    preference: str = Field(default="", max_length=300)


class MemoryWriteRequest(BaseModel):
    kind: str
    text: str = Field(min_length=1, max_length=2000)
    reason: str | None = None
    session_id: str = "memory"


def _session_id(value: str) -> str:
    if not _SESSION_ID.fullmatch(value or ""):
        raise HTTPException(status_code=400, detail="session_id 只能是 1-64 位字母、数字、下划线或连字符")
    return value


def _pc_error(error: PowerContextError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"PowerContext 不可用：{error}。请先运行 scripts/start_powercontext.* 并确认 {settings.powercontext_url} 可访问。",
    )


@router.post("/ask")
def api_ask(request: AskRequest) -> dict:
    session_id = _session_id(request.session_id)
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    started = time.perf_counter()
    repo.start_session(session_id, settings.user_id, question)
    repo.set_session_topic(session_id, question)

    seek = hybrid.search(
        question,
        mode=request.mode,
        subject=request.subject,
        doc_id=request.doc_id,
        top_k=request.top_k,
        session_id=session_id,
    )
    retrieval_ms = int((time.perf_counter() - started) * 1000)

    memory_started = time.perf_counter()
    try:
        memory = memory_service.build_memory_context(question, session_id=session_id, top_k=8)
    except PowerContextError as error:
        raise _pc_error(error) from error
    memory_ms = int((time.perf_counter() - memory_started) * 1000)

    llm_answer, llm_meta = answerer.llm_answer(
        question,
        seek["results"],
        memory["block"],
        session_id=session_id,
    )
    mode = "llm" if llm_answer else "evidence"
    answer = llm_answer or answerer.evidence_answer(question, seek["results"], memory["memories"])

    citations = [
        {
            "index": index,
            "chunk_id": hit["chunk_id"],
            "doc_id": hit["doc_id"],
            "doc_title": hit["doc_title"],
            "section": hit["section"],
            "page": hit["page"],
            "score": hit["score"],
            "relevance": hit["relevance"],
        }
        for index, hit in enumerate(seek["results"], start=1)
    ]
    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_APP,
        operation="answer",
        input_text=question,
        result_count=len(seek["results"]),
        summary=(
            f"{mode} 回答；引用 {len(citations)} 条 chunk；"
            f"注入记忆 {len(memory['memories'])} 条；检索 {retrieval_ms}ms / 记忆 {memory_ms}ms"
        ),
        payload={
            "mode": mode,
            "seekdb_trace_id": seek["trace_id"],
            "memory_artifact_ids": [item["artifact_id"] for item in memory["memories"]],
            "memory_counts": memory["counts"],
            "citations": [
                {"chunk_id": item["chunk_id"], "section": item["section"], "score": item["score"]}
                for item in citations
            ],
            "llm": llm_meta,
            "timing_ms": {"retrieval": retrieval_ms, "memory": memory_ms},
        },
    )
    repo.save_trace(event)

    return {
        "question": question,
        "session_id": session_id,
        "mode": mode,
        "answer": answer,
        "results": seek["results"],
        "citations": citations,
        "keywords": seek["keywords"],
        "notes": seek["notes"],
        "injected_memories": memory["memories"],
        "memory_counts": memory["counts"],
        "memory_block": memory["block"],
        "scope_id": memory["scope_id"],
        "trace_ids": {
            "seekdb": seek["trace_id"],
            "memory": [memory["trace_id"]],
            "answer": event.trace_id,
            "llm": llm_meta.get("trace_id"),
        },
        "timing_ms": {"retrieval": retrieval_ms, "memory": memory_ms},
    }


@router.post("/session/close")
def api_close_session(request: CloseRequest) -> dict:
    session_id = _session_id(request.session_id)
    try:
        return session_coach.close_session(
            session_id,
            topic=request.topic,
            struggles=request.struggles,
            preference=request.preference,
        )
    except PowerContextError as error:
        raise _pc_error(error) from error


@router.get("/memory")
def api_memory(
    limit: int = Query(default=50, ge=1, le=100),
    session_id: str = Query(default="memory"),
) -> dict:
    session_id = _session_id(session_id)
    try:
        return {
            "scope_id": memory_service.scope_id(),
            "memories": memory_service.list_memories(limit=limit, session_id=session_id),
        }
    except PowerContextError as error:
        raise _pc_error(error) from error


@router.get("/memory/status")
def api_memory_status() -> dict:
    return memory_service.status()


@router.post("/memory")
def api_memory_write(request: MemoryWriteRequest) -> dict:
    session_id = _session_id(request.session_id)
    try:
        return memory_service.write_memory(
            request.kind,
            request.text,
            session_id=session_id,
            reason=request.reason or "用户手动写入",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except PowerContextError as error:
        raise _pc_error(error) from error


@router.get("/session/{session_id}")
def api_session(session_id: str) -> dict:
    session_id = _session_id(session_id)
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="没有这个会话")
    return {
        "session": session,
        "trace_counts": repo.trace_counts(session_id),
        "evidence": repo.session_evidence(session_id),
    }
