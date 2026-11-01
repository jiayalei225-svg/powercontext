"""Trace contract shared by the recorder, the API and the UI.

Every seekdb query and every PowerContext read/write produces one of these.
The fields mirror ``study_traces`` so filling the table is a single insert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

LAYER_SEEKDB = "seekdb"
LAYER_POWERCONTEXT = "powercontext"
LAYER_APP = "app"
LAYER_LLM = "llm"


def new_trace_id() -> str:
    return f"tr_{uuid4().hex[:16]}"


@dataclass
class TraceEvent:
    session_id: str
    layer: str
    operation: str
    input_text: str
    result_count: int
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=new_trace_id)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_row(self) -> tuple:
        return (
            self.trace_id,
            self.session_id,
            self.ts,
            self.layer,
            self.operation,
            self.input_text,
            self.result_count,
            self.summary,
            _dumps(self.payload),
        )


def _dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
