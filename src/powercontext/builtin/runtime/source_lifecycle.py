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

"""Source-driven lifecycle state for Memory and Topic Memory.

The graph is registered explicitly by its single writer. Availability is
derived from Source events through each node's ``all`` or ``any`` policy, and
Memory entries are kept in their native active or inactive state so existing
list, search, and Context paths observe the same decision.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import Memory
from powercontext.builtin.artifacts.topic_memory import TopicMemory
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.source_lifecycle import (
    LifecycleKind,
    LifecyclePolicy,
    LifecycleReference,
    SourceLifecycleRepository,
    StoredLifecycleEvent,
    StoredLifecycleNode,
)
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.errors import PowerContextError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory import MemoryEntryVersion, MemoryManifestEntry, MemoryService
    from powercontext.builtin.runtime.application import BuiltinRuntime

_MAX_NODE_ID_LENGTH = 256
_REGISTRATION_REASON = "source lifecycle registration"


class SourceLifecycleError(ValueError):
    """Reject an invalid lifecycle registration, event, or resolution."""

    def __init__(self, code: str) -> None:
        messages = {
            "database": "Source lifecycle requires a relational built-in Runtime",
            "derived-policy": "a derived node requires an all or any policy",
            "event": "event must be a SourceLifecycleEvent",
            "inactive-node": "node is not available for generation",
            "memory-artifact": "Memory citation belongs to a different Memory artifact",
            "memory-citation": "citation must be a MemoryCitation",
            "memory-entry": "registered Memory entry is no longer present",
            "memory-family": "citation must reference the Memory family",
            "memory-unreadable": "registered Memory entry is no longer readable",
            "memory-version": "registered Memory entry version is no longer current",
            "missing-parent": "a parent node is not registered",
            "node-id": "node id must be a non-blank string",
            "node-id-length": f"node id must not exceed {_MAX_NODE_ID_LENGTH} characters",
            "parents": "parents must be a non-empty collection of unique node ids",
            "policy": "policy must be 'all' or 'any'",
            "purpose": "purpose must be 'generation' or 'audit'",
            "registration-conflict": "node is already registered with a different binding",
            "revision": "revision must be a positive integer",
            "revision-mismatch": "event revision does not match the Source registration",
            "self-parent": "a node cannot depend on itself",
            "sequence-regressed": "event sequence regressed",
            "sequence-reused": "event sequence was reused with different content",
            "source-reference": "source_ref must be a SourceRef",
            "topic-family": "artifact_ref must reference the topic-memory family",
            "topic-reference": "artifact_ref must be an ArtifactRef",
            "unreadable-reference": "registered reference is not readable",
            "unregistered-node": "node is not registered",
            "unregistered-source": "event references an unregistered Source",
        }
        super().__init__(messages.get(code, code))


class SourceLifecycleEvent(BaseModel):
    """One caller-supplied availability change for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: StrictStr
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: StrictStr

    @field_validator("node_id", "reason")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value


class ScopedSourceLifecycleApplication:
    """Register one Scope's evidence graph and apply Source lifecycle events."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None, scope_id: str) -> None:
        self._runtime = runtime
        self._database = database
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(
        self,
        node_id: str,
        source_ref: SourceRef,
        /,
        *,
        revision: int,
    ) -> None:
        """Register one available Source at an explicit lifecycle revision."""

        node_id = _validate_node_id(node_id)
        revision = _positive_revision(revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source-reference")
        await self._register(
            node_id,
            kind="source",
            reference=source_ref,
            parents=(),
            policy=None,
            revision=revision,
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        """Register one Memory entry whose availability follows its parents."""

        node_id = _validate_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("memory-citation")
        if citation.memory_ref.family != Memory.family:
            raise SourceLifecycleError("memory-family")
        parsed_parents = _validate_parents(parents)
        parsed_policy = _validate_policy(policy)
        await self._register(
            node_id,
            kind="memory",
            reference=citation,
            parents=parsed_parents,
            policy=parsed_policy,
            revision=None,
        )

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        /,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        """Register one Topic Memory Revision whose availability follows its parents."""

        node_id = _validate_node_id(node_id)
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("topic-reference")
        if artifact_ref.family != TopicMemory.family:
            raise SourceLifecycleError("topic-family")
        parsed_parents = _validate_parents(parents)
        parsed_policy = _validate_policy(policy)
        await self._register(
            node_id,
            kind="topic",
            reference=artifact_ref,
            parents=parsed_parents,
            policy=parsed_policy,
            revision=None,
        )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Apply one Source event and return every active node id in sorted order."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event")
        database = self._require_database()
        repository = SourceLifecycleRepository()
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            async with database.transaction() as connection:
                nodes = await repository.list_nodes(connection, self.scope_id)
            by_id = {node.node_id: node for node in nodes}
            source = by_id.get(event.node_id)
            if source is None or source.kind != "source":
                raise SourceLifecycleError("unregistered-source")
            if _exact_replay(source, event):
                return _active_ids(nodes)

            updates = _propagate(nodes, event)
            changed_memory = tuple(
                updates[node.node_id]
                for node in nodes
                if node.kind == "memory" and updates[node.node_id].active != node.active
            )
            for node in changed_memory:
                await self._converge_memory(node.reference, active=node.active, reason=event.reason)

            async with database.transaction() as connection:
                for node in updates.values():
                    if node != by_id[node.node_id]:
                        await repository.update_state(connection, node)
                await repository.insert_event(
                    connection,
                    StoredLifecycleEvent(
                        scope_id=self.scope_id,
                        node_id=event.node_id,
                        sequence=event.sequence,
                        revision=event.revision,
                        available=event.available,
                        reason=event.reason,
                    ),
                )
            return _active_ids(tuple(updates.values()))

    async def resolve(
        self,
        node_id: str,
        /,
        *,
        purpose: Literal["generation", "audit"] = "generation",
    ) -> LifecycleReference:
        """Resolve the original reference when the requested purpose permits it."""

        node_id = _validate_node_id(node_id)
        if purpose not in ("generation", "audit"):
            raise SourceLifecycleError("purpose")
        database = self._require_database()
        async with self._runtime._scope_operation(self.scope_id), database.transaction() as connection:
            node = await SourceLifecycleRepository().get_node(connection, self.scope_id, node_id)
        if node is None:
            raise SourceLifecycleError("unregistered-node")
        if purpose == "generation" and not node.active:
            raise SourceLifecycleError("inactive-node")
        return node.reference

    async def _inactive_topic_references(self) -> tuple[ArtifactRef, ...]:
        """Return Topic revisions excluded from native search and Context recall."""

        if self._database is None:
            return ()
        async with self._database.transaction() as connection:
            return await SourceLifecycleRepository().inactive_topic_references(connection, self.scope_id)

    async def _register(
        self,
        node_id: str,
        *,
        kind: LifecycleKind,
        reference: LifecycleReference,
        parents: tuple[str, ...],
        policy: LifecyclePolicy | None,
        revision: int | None,
    ) -> None:
        database = self._require_database()
        repository = SourceLifecycleRepository()
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            async with database.transaction() as connection:
                nodes = await repository.list_nodes(connection, self.scope_id)
            existing = next((node for node in nodes if node.node_id == node_id), None)
            if existing is not None:
                if _same_registration(
                    existing,
                    kind=kind,
                    reference=reference,
                    parents=parents,
                    policy=policy,
                    revision=revision,
                ):
                    return
                raise SourceLifecycleError("registration-conflict")

            by_id = {node.node_id: node for node in nodes}
            for parent in parents:
                if parent == node_id:
                    raise SourceLifecycleError("self-parent")
                if parent not in by_id:
                    raise SourceLifecycleError("missing-parent")
            active = True if kind == "source" else _derived_active(by_id, parents=parents, policy=policy)
            await self._require_readable(kind, reference)
            if kind == "memory":
                await self._converge_memory(reference, active=active, reason=_REGISTRATION_REASON)

            ordinal = 0 if not nodes else max(node.ordinal for node in nodes) + 1
            record = StoredLifecycleNode(
                scope_id=self.scope_id,
                node_id=node_id,
                ordinal=ordinal,
                kind=kind,
                active=active,
                parents=parents,
                policy=policy,
                reference=reference,
                revision=revision,
            )
            async with database.transaction() as connection:
                await repository.insert_node(connection, record)

    async def _require_readable(self, kind: LifecycleKind, reference: LifecycleReference) -> None:
        try:
            if kind == "source":
                source_ref = cast(SourceRef, reference)
                await self._runtime.records.for_scope(self.scope_id).get_source(
                    source_ref.source_type,
                    source_ref.source_id,
                )
            elif kind == "memory":
                citation = cast(MemoryCitation, reference)
                await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
            else:
                artifact_ref = cast(ArtifactRef, reference)
                await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                    artifact_ref.family,
                    artifact_ref.artifact_id,
                    artifact_ref.revision,
                )
        except PowerContextError as error:
            raise SourceLifecycleError("unreadable-reference") from error

    async def _converge_memory(
        self,
        citation: LifecycleReference,
        *,
        active: bool,
        reason: str,
    ) -> None:
        citation = cast(MemoryCitation, citation)
        async with self._runtime._context(self.scope_id) as context:
            service: MemoryService = context.artifacts.memory
            if citation.memory_ref.artifact_id != context.artifacts.memory_artifact_id:
                raise SourceLifecycleError("memory-artifact")
            try:
                memory, entries = await service.head_entries(context.artifacts.memory_artifact_id)
            except PowerContextError as error:
                raise SourceLifecycleError("memory-unreadable") from error
            manifest_entry = _manifest_entry(memory, citation)
            current = _current_entry(entries, citation)
            if (
                manifest_entry.entry_version_id != citation.entry_version_id
                or current.entry_version_id != citation.entry_version_id
            ):
                raise SourceLifecycleError("memory-version")
            if (manifest_entry.state == "active") == active:
                return
            if active:
                await service.reactivate(memory, entries=(current,), reason=reason)
            else:
                await service.forget(memory, entries=(current,), reason=reason)

    def _require_database(self) -> AsyncDatabase:
        if self._database is None:
            raise SourceLifecycleError("database")
        return self._database


class LifecycleApplication:
    """Select the scoped Source lifecycle application service."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None) -> None:
        self._runtime = runtime
        self._database = database

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleApplication:
        return ScopedSourceLifecycleApplication(self._runtime, self._database, scope_id)


def _validate_node_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("node-id")
    if len(value) > _MAX_NODE_ID_LENGTH:
        raise SourceLifecycleError("node-id-length")
    return value


def _positive_revision(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise SourceLifecycleError("revision")
    return value


def _validate_parents(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise SourceLifecycleError("parents")
    parents = tuple(_validate_node_id(parent) for parent in value)
    if not parents or len(set(parents)) != len(parents):
        raise SourceLifecycleError("parents")
    return parents


def _validate_policy(value: object) -> LifecyclePolicy:
    if not isinstance(value, str) or value not in {"all", "any"}:
        raise SourceLifecycleError("policy")
    return value


def _same_registration(
    existing: StoredLifecycleNode,
    *,
    kind: LifecycleKind,
    reference: LifecycleReference,
    parents: tuple[str, ...],
    policy: LifecyclePolicy | None,
    revision: int | None,
) -> bool:
    if existing.kind != kind or existing.reference != reference:
        return False
    if kind == "source":
        return existing.revision == revision
    return existing.policy == policy and len(existing.parents) == len(parents) and set(existing.parents) == set(parents)


def _derived_active(
    nodes: dict[str, StoredLifecycleNode],
    *,
    parents: tuple[str, ...],
    policy: LifecyclePolicy | None,
) -> bool:
    if policy is None:
        raise SourceLifecycleError("derived-policy")
    return _policy_active(nodes, parents, policy)


def _policy_active(
    nodes: dict[str, StoredLifecycleNode],
    parents: tuple[str, ...],
    policy: LifecyclePolicy,
) -> bool:
    states: list[bool] = []
    for parent in parents:
        parent_node = nodes.get(parent)
        if parent_node is None:
            raise SourceLifecycleError("missing-parent")
        states.append(parent_node.active)
    return all(states) if policy == "all" else any(states)


def _exact_replay(source: StoredLifecycleNode, event: SourceLifecycleEvent) -> bool:
    """Validate a Source event and report whether it repeats the last accepted one."""

    if source.revision != event.revision:
        raise SourceLifecycleError("revision-mismatch")
    if source.sequence is None:
        return False
    if event.sequence < source.sequence:
        raise SourceLifecycleError("sequence-regressed")
    if event.sequence > source.sequence:
        return False
    if event.available == source.last_available and event.reason == source.last_reason:
        return True
    raise SourceLifecycleError("sequence-reused")


def _propagate(nodes: tuple[StoredLifecycleNode, ...], event: SourceLifecycleEvent) -> dict[str, StoredLifecycleNode]:
    by_id = {node.node_id: node for node in nodes}
    updates = dict(by_id)
    source = by_id[event.node_id]
    updates[event.node_id] = replace(
        source,
        active=event.available,
        sequence=event.sequence,
        last_available=event.available,
        last_reason=event.reason,
    )
    for node in nodes:
        if node.kind == "source":
            continue
        policy = node.policy
        if policy is None:
            raise SourceLifecycleError("derived-policy")
        active = _policy_active(updates, node.parents, policy)
        if active != node.active:
            updates[node.node_id] = replace(node, active=active)
    return updates


def _active_ids(nodes: tuple[StoredLifecycleNode, ...]) -> list[str]:
    return sorted(node.node_id for node in nodes if node.active)


def _manifest_entry(memory: Memory, citation: MemoryCitation) -> MemoryManifestEntry:
    item = next(
        (entry for entry in memory.content.manifest.entries if entry.entry_id == citation.entry_id),
        None,
    )
    if item is None:
        raise SourceLifecycleError("memory-entry")
    return item


def _current_entry(entries: tuple[MemoryEntryVersion, ...], citation: MemoryCitation) -> MemoryEntryVersion:
    item = next((entry for entry in entries if entry.entry_id == citation.entry_id), None)
    if item is None:
        raise SourceLifecycleError("memory-entry")
    return item


__all__ = [
    "LifecycleApplication",
    "ScopedSourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
