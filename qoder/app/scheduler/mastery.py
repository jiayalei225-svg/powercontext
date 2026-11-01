"""Mastery scoring and a simplified SM-2 schedule.

Two numbers live here and nowhere else:

* ``score``    - a 0..1 mastery estimate used for ordering and the home page;
* ``interval`` - the next review gap in days, adjusted with an SM-2-like ease.

The score reacts quickly (a correct answer raises it, a wrong one lowers it) and
decays while the point is not practiced. The interval follows the usual
1 day -> 3 days -> interval * ease progression; a lapse resets it and brings the
point back within the same day instead of waiting a full day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import settings

DEFAULT_SCORE = 0.5
DEFAULT_EASE = 2.5
MAX_EASE = 3.0
MIN_EASE = 1.3
MAX_INTERVAL_DAYS = 180
LAPSE_DELAY_MINUTES = 30


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decay(score: float, last_practiced_at: datetime | None, now: datetime) -> float:
    if last_practiced_at is None:
        return score
    days = max(0.0, (now - last_practiced_at).total_seconds() / 86400)
    if days <= 0 or settings.decay_days <= 0:
        return score
    factor = min(1.0, max(0.0, settings.decay_factor))
    return score * (factor ** (days / settings.decay_days))


def update(
    mastery: dict[str, Any] | None,
    correct: bool,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    row = mastery or {}
    score = float(row.get("score") if row.get("score") is not None else DEFAULT_SCORE)
    ease = float(row.get("ease") if row.get("ease") is not None else DEFAULT_EASE)
    interval = int(row.get("interval_days") or 0)
    repetitions = int(row.get("repetitions") or 0)
    lapses = int(row.get("lapses") or 0)
    last = row.get("last_practiced_at")

    score = _decay(score, last if isinstance(last, datetime) else None, now)

    if correct:
        score += settings.mastery_alpha * (1.0 - score)
        ease = min(MAX_EASE, ease + 0.1)
        repetitions += 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 3
        else:
            interval = max(1, round(interval * ease))
        interval = min(MAX_INTERVAL_DAYS, interval)
        next_review = now + timedelta(days=interval)
    else:
        score *= 1.0 - settings.mastery_beta
        ease = max(MIN_EASE, ease - 0.2)
        repetitions = 0
        lapses += 1
        interval = 1
        next_review = now + timedelta(minutes=LAPSE_DELAY_MINUTES)

    return {
        "kp_id": row.get("kp_id", ""),
        "score": round(min(0.99, max(0.05, score)), 4),
        "ease": round(ease, 4),
        "interval_days": interval,
        "repetitions": repetitions,
        "lapses": lapses,
        "last_practiced_at": now,
        "next_review_at": next_review,
        "updated_at": now,
    }


def describe_next(next_review_at: Any, *, now: datetime | None = None) -> str:
    if not next_review_at:
        return "未练习"
    if isinstance(next_review_at, str):
        try:
            next_review_at = datetime.fromisoformat(next_review_at.replace("Z", ""))
        except ValueError:
            return next_review_at
    if isinstance(next_review_at, datetime):
        delta = next_review_at - (now or _now())
        minutes = int(delta.total_seconds() // 60)
        if minutes <= 0:
            return "已到期"
        if minutes < 60:
            return f"{minutes} 分钟后"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} 小时后"
        return f"{hours // 24} 天后"
    return str(next_review_at)
