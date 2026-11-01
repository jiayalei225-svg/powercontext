"""HTTP surface for today's review queue, quiz generation and grading."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..scheduler import plan, quiz, review
from ..seekdb import repo

router = APIRouter(prefix="/api", tags=["review"])

_SESSION = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class GenerateRequest(BaseModel):
    limit: int = Field(default=5, ge=1, le=30)
    subject: str | None = None
    session_id: str = "quiz"


class AnswerItem(BaseModel):
    question_id: str = Field(min_length=1, max_length=64)
    chosen: str = ""


class SubmitRequest(BaseModel):
    session_id: str = "quiz"
    note: str = Field(default="", max_length=500)
    answers: list[AnswerItem] = Field(min_length=1, max_length=50)


class PlanRequest(BaseModel):
    session_id: str = "plan"
    days: int = Field(default=3, ge=1, le=14)
    limit: int = Field(default=5, ge=1, le=10)


def _session(value: str) -> str:
    if not _SESSION.match(value or ""):
        raise HTTPException(status_code=400, detail="session_id 格式不合法")
    return value


def _guard(callable_, *args, **kwargs):
    try:
        return callable_(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/review/today")
def api_review_today(
    subject: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    session_id: str = Query(default="review"),
) -> dict:
    return _guard(review.today, subject, limit, _session(session_id))


@router.get("/knowledge")
def api_knowledge(subject: str | None = Query(default=None)) -> dict:
    return _guard(lambda: {"knowledge_points": repo.list_knowledge_points(subject)})


@router.post("/quiz/generate")
def api_quiz_generate(request: GenerateRequest) -> dict:
    return _guard(
        quiz.generate,
        limit=request.limit,
        subject=request.subject,
        session_id=_session(request.session_id),
    )


@router.post("/quiz/submit")
def api_quiz_submit(request: SubmitRequest) -> dict:
    return _guard(
        quiz.submit,
        [item.model_dump() for item in request.answers],
        session_id=_session(request.session_id),
        note=request.note,
    )


@router.post("/review/plan")
def api_review_plan(request: PlanRequest) -> dict:
    return _guard(
        plan.build,
        days=request.days,
        limit=request.limit,
        session_id=_session(request.session_id),
    )
