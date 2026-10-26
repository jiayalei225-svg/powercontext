# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Immutable Pi session events and incremental branch-history collection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, JsonValue, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import TEXT_EVIDENCE_PROJECTION_KEY, AdapterSourceDefinition, TextEvidence
from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
)
from powercontext.sources.models import Source, SourceMaterialization

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
_CHECKPOINT_VERSION = 1


class PiSessionInput(BaseModel):
    """An offline Pi v3 session archive and one selected branch leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible raw session event with its complete input record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_identity(self) -> PiEventInput:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")  # noqa: TRY003
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id must be a non-empty string")  # noqa: TRY003
        return self


class PiEventSource(Source):
    """Captured Pi session event whose identity is session plus event id."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_source_identity(self) -> PiEventSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the Source name")  # noqa: TRY003
        return self


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Return the delimiter-safe identity of one Pi session event."""

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id must be a non-empty string")  # noqa: TRY003
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a non-empty string")  # noqa: TRY003
    identity = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pi event source id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


def parse_pi_session(value: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Parse one branch of a Pi v3 JSONL archive into visible raw events."""

    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be strictly valid UTF-8") from error  # noqa: TRY003

    records: list[dict[str, JsonValue]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Pi session line is not valid JSON: {error}") from error  # noqa: TRY003
        if not isinstance(record, dict):
            raise ValueError("Pi session records must be JSON objects")  # noqa: TRY003
        records.append(record)

    if not records:
        raise ValueError("Pi session must start with a session header")  # noqa: TRY003
    header = records[0]
    if header.get("type") != "session" or header.get("version") != 3:
        raise ValueError("Pi session header must declare type=session and version=3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Pi session header must declare a non-empty string id")  # noqa: TRY003

    nodes = records[1:]
    positions: dict[str, int] = {}
    for position, node in enumerate(nodes):
        event_id = node.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Pi session entries must declare a non-empty string id")  # noqa: TRY003
        if event_id in positions:
            raise ValueError(f"duplicate Pi session entry id {event_id!r}")  # noqa: TRY003
        if "parentId" not in node:
            raise ValueError(f"Pi session entry {event_id!r} must declare parentId")  # noqa: TRY003
        parent_id = node["parentId"]
        if parent_id is not None:
            if not isinstance(parent_id, str):
                raise ValueError(f"Pi session entry {event_id!r} has a non-string parentId")  # noqa: TRY003
            if parent_id not in positions:
                raise ValueError(  # noqa: TRY003
                    f"Pi session entry {event_id!r} references missing parent {parent_id!r}"
                )
        positions[event_id] = position

    if not nodes:
        raise ValueError("Pi session does not contain any entries to select a leaf from")  # noqa: TRY003

    leaf_id = nodes[-1].get("id") if value.leaf_id is None else value.leaf_id
    if not isinstance(leaf_id, str) or leaf_id not in positions:
        raise ValueError(f"Pi session leaf {leaf_id!r} does not exist")  # noqa: TRY003

    chain: list[int] = []
    visited: set[str] = set()
    current: str | None = leaf_id
    while current is not None:
        if current in visited:
            raise ValueError("Pi session entries form a cycle")  # noqa: TRY003
        visited.add(current)
        position = positions[current]
        chain.append(position)
        current = nodes[position].get("parentId")
    chain.reverse()

    events: list[PiEventInput] = []
    for position in chain:
        node = nodes[position]
        rendered = _render_visible_event(node)
        if rendered is None:
            continue
        role, body = rendered
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=node["id"],
                parent_id=node.get("parentId"),
                event_type=node.get("type"),
                role=role,
                content=f"{role}: {body}",
                record=node,
            )
        )
    return tuple(events)


class PiSessionConnector:
    """Import one selected Pi branch incrementally through the public lifecycle."""

    name = PI_SESSION_CONNECTOR_NAME
    version = "1"
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(PiSessionInput(content=self.path.read_bytes(), leaf_id=self.leaf_id))
        checkpoint = _load_checkpoint(session.checkpoint)
        if not events:
            return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=session.checkpoint)

        session_id = events[0].session_id
        imported = checkpoint["sessions"].get(session_id, {}).get("events", {})
        for event in events:
            fingerprint = _record_fingerprint(event.record)
            if event.event_id in imported and imported[event.event_id] != fingerprint:
                raise ValueError(  # noqa: TRY003
                    f"Pi event {event.event_id!r} was rewritten after it was imported"
                )

        new_events = tuple(event for event in events if event.event_id not in imported)
        if not new_events:
            return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=session.checkpoint)

        item_ids = tuple(pi_event_source_id(event.session_id, event.event_id) for event in new_events)
        for item_id, event in zip(item_ids, new_events, strict=True):
            await session.submit(item_id, PI_EVENT_SOURCE_NAME, event)

        checkpoint["sessions"].setdefault(session_id, {"events": {}})["events"].update(
            {event.event_id: _record_fingerprint(event.record) for event in new_events}
        )
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint)


class PiEventSourceAdapter:
    """Resolve and read captured Pi session events."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        identity = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one captured Pi event as complete textual evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    projections=(PiEventTextEvidenceProjection(),),
)


def _render_visible_event(node: dict[str, JsonValue]) -> tuple[str, str] | None:
    event_type = node.get("type")
    if event_type == "message":
        return _render_message(node.get("message"))
    if event_type in {"compaction", "branch_summary"}:
        if not isinstance(event_type, str):
            return None
        summary = node.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        return event_type, summary
    if event_type == "custom_message":
        body = _render_content(node.get("content"))
        if body is None or not body.strip():
            return None
        return "custom", body
    return None


def _render_message(message: JsonValue) -> tuple[str, str] | None:
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    if not isinstance(role, str) or not role:
        return None
    if role == "toolResult":
        text = _render_content(message.get("content")) or ""
        tool_name = message.get("toolName")
        tool_call_id = message.get("toolCallId")
        name = tool_name if isinstance(tool_name, str) and tool_name else "unknown"
        call_id = tool_call_id if isinstance(tool_call_id, str) else ""
        return role, f"[tool_result {name} {call_id}] {text}"
    if role == "bashExecution":
        command = message.get("command")
        if not isinstance(command, str) or not command:
            return None
        output = message.get("output")
        text = output if isinstance(output, str) else ""
        return role, f"$ {command}\n{text}"
    body = _render_content(message.get("content"))
    if body is None or not body.strip():
        return None
    return role, body


def _render_content(content: JsonValue) -> str | None:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block_type == "toolCall":
            parts.append(_render_tool_call(block))
    return "\n".join(parts) if parts else None


def _render_tool_call(block: dict[str, JsonValue]) -> str:
    name = block.get("name")
    call_id = block.get("id")
    arguments = block.get("arguments", {})
    rendered_name = name if isinstance(name, str) else ""
    rendered_id = call_id if isinstance(call_id, str) else ""
    encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"[tool_call {rendered_name} {rendered_id}] {encoded}"


def _record_fingerprint(record: dict[str, JsonValue]) -> str:
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_checkpoint(value: JsonValue) -> dict[str, JsonValue]:
    if value is None:
        return {"version": _CHECKPOINT_VERSION, "sessions": {}}
    if not isinstance(value, dict) or value.get("version") != _CHECKPOINT_VERSION:
        raise ValueError("unsupported Pi session checkpoint")  # noqa: TRY003
    sessions = value.get("sessions")
    if not isinstance(sessions, dict):
        raise ValueError("unsupported Pi session checkpoint")  # noqa: TRY003
    normalized: dict[str, JsonValue] = {}
    for session_id, payload in sessions.items():
        if not isinstance(session_id, str) or not isinstance(payload, dict):
            raise ValueError("unsupported Pi session checkpoint")  # noqa: TRY003
        records = payload.get("events")
        if not isinstance(records, dict):
            raise ValueError("unsupported Pi session checkpoint")  # noqa: TRY003
        if not all(isinstance(key, str) and isinstance(item, str) for key, item in records.items()):
            raise ValueError("unsupported Pi session checkpoint")  # noqa: TRY003
        normalized[session_id] = {"events": dict(records)}
    return {"version": _CHECKPOINT_VERSION, "sessions": normalized}


__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
