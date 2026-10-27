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

"""Persistence for Source-driven lifecycle registrations and events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODES_TABLE,
)
from powercontext.sources import SourceRef

LifecycleKind = Literal["source", "memory", "topic"]
LifecyclePolicy = Literal["all", "any"]
LifecycleReference = SourceRef | MemoryCitation | ArtifactRef


@dataclass(frozen=True, slots=True)
class StoredLifecycleNode:
    """One registered lifecycle node and its persisted derived state."""

    scope_id: str
    node_id: str
    ordinal: int
    kind: LifecycleKind
    active: bool
    parents: tuple[str, ...]
    policy: LifecyclePolicy | None
    reference: LifecycleReference
    revision: int | None = None
    sequence: int | None = None
    last_available: bool | None = None
    last_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StoredLifecycleEvent:
    """One accepted lifecycle event, retained for replay and audit."""

    scope_id: str
    node_id: str
    sequence: int
    revision: int
    available: bool
    reason: str


class SourceLifecycleRepository:
    """Read and write lifecycle registrations without owning transactions."""

    async def list_nodes(self, connection: AsyncConnection, scope_id: str, /) -> tuple[StoredLifecycleNode, ...]:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        rows = (
            await connection.execute(select(table).where(table.c.scope_id == scope_id).order_by(table.c.ordinal))
        ).mappings()
        return tuple(_node_from_row(row) for row in rows)

    async def get_node(
        self,
        connection: AsyncConnection,
        scope_id: str,
        node_id: str,
        /,
    ) -> StoredLifecycleNode | None:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        statement = select(table).where(table.c.scope_id == scope_id, table.c.node_id == node_id)
        row = (await connection.execute(statement)).mappings().first()
        return None if row is None else _node_from_row(row)

    async def insert_node(self, connection: AsyncConnection, node: StoredLifecycleNode, /) -> None:
        await connection.execute(
            SOURCE_LIFECYCLE_NODES_TABLE.insert().values(
                scope_id=node.scope_id,
                node_id=node.node_id,
                ordinal=node.ordinal,
                kind=node.kind,
                active=node.active,
                parents=_dump_parents(node.parents),
                policy=node.policy,
                reference=_dump_reference(node.kind, node.reference),
                revision=node.revision,
                sequence=node.sequence,
                last_available=node.last_available,
                last_reason=node.last_reason,
            )
        )

    async def update_state(self, connection: AsyncConnection, node: StoredLifecycleNode, /) -> None:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        await connection.execute(
            table
            .update()
            .where(table.c.scope_id == node.scope_id, table.c.node_id == node.node_id)
            .values(
                active=node.active,
                sequence=node.sequence,
                last_available=node.last_available,
                last_reason=node.last_reason,
            )
        )

    async def insert_event(self, connection: AsyncConnection, event: StoredLifecycleEvent, /) -> None:
        await connection.execute(
            SOURCE_LIFECYCLE_EVENTS_TABLE.insert().values(
                scope_id=event.scope_id,
                node_id=event.node_id,
                sequence=event.sequence,
                revision=event.revision,
                available=event.available,
                reason=event.reason,
            )
        )

    async def inactive_topic_references(
        self,
        connection: AsyncConnection,
        scope_id: str,
        /,
    ) -> tuple[ArtifactRef, ...]:
        table = SOURCE_LIFECYCLE_NODES_TABLE
        rows = await connection.scalars(
            select(table.c.reference).where(
                table.c.scope_id == scope_id,
                table.c.kind == "topic",
                table.c.active.is_(False),
            )
        )
        return tuple(cast(ArtifactRef, _load_reference("topic", payload)) for payload in rows)


def _node_from_row(row: Mapping[str, Any]) -> StoredLifecycleNode:
    values = dict(row)
    kind = values["kind"]
    if kind not in {"source", "memory", "topic"}:
        raise ValueError("stored lifecycle node has an unknown kind")  # noqa: TRY003
    policy = values["policy"]
    if policy not in {None, "all", "any"}:
        raise ValueError("stored lifecycle node has an unknown policy")  # noqa: TRY003
    return StoredLifecycleNode(
        scope_id=str(values["scope_id"]),
        node_id=str(values["node_id"]),
        ordinal=int(values["ordinal"]),
        kind=kind,
        active=bool(values["active"]),
        parents=_load_parents(values["parents"]),
        policy=policy,
        reference=_load_reference(kind, values["reference"]),
        revision=None if values["revision"] is None else int(values["revision"]),
        sequence=None if values["sequence"] is None else int(values["sequence"]),
        last_available=None if values["last_available"] is None else bool(values["last_available"]),
        last_reason=None if values["last_reason"] is None else str(values["last_reason"]),
    )


def _dump_parents(parents: tuple[str, ...]) -> bytes:
    return json.dumps(list(parents), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_parents(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("stored lifecycle parents are not bytes")  # noqa: TRY003
    values = json.loads(bytes(payload))
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError("stored lifecycle parents are malformed")  # noqa: TRY003
    return tuple(values)


def _dump_reference(kind: LifecycleKind, reference: LifecycleReference) -> bytes:
    if kind == "source" and isinstance(reference, SourceRef):
        return reference.model_dump_json().encode()
    if kind == "memory" and isinstance(reference, MemoryCitation):
        return reference.model_dump_json().encode()
    if kind == "topic" and isinstance(reference, ArtifactRef):
        return reference.model_dump_json().encode()
    raise ValueError("stored lifecycle reference does not match its kind")  # noqa: TRY003


def _load_reference(kind: LifecycleKind, payload: object) -> LifecycleReference:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("stored lifecycle reference is not bytes")  # noqa: TRY003
    data = bytes(payload)
    if kind == "source":
        return SourceRef.model_validate_json(data, strict=True)
    if kind == "memory":
        return MemoryCitation.model_validate_json(data, strict=True)
    return ArtifactRef.model_validate_json(data, strict=True)


__all__ = [
    "LifecycleKind",
    "LifecyclePolicy",
    "LifecycleReference",
    "SourceLifecycleRepository",
    "StoredLifecycleEvent",
    "StoredLifecycleNode",
]
