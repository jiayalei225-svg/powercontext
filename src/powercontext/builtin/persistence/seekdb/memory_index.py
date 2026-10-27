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

"""seekdb Memory index that fetches full-text and vector candidates in one SQL."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pyobvector import VECTOR
from sqlalchemy import Table, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryCapabilities,
    MemoryProjection,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import (
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

_HYBRID_FTS_BRANCH = """
SELECT
    CAST('fts' AS CHAR(16)) AS channel,
    f.memory_artifact_id,
    f.head_revision,
    f.entry_id,
    f.entry_version_id,
    v.text,
    MATCH(f.searchable_text) AGAINST(:analyzed_query) AS relevance,
    CAST(NULL AS DECIMAL(65, 30)) AS distance
FROM pc_memory_entry_heads AS f
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = f.scope_id
 AND v.memory_artifact_id = f.memory_artifact_id
 AND v.entry_version_id = f.entry_version_id
WHERE f.scope_id = :scope_id
  AND f.memory_artifact_id IN :memory_artifact_ids
  AND MATCH(f.searchable_text) AGAINST(:analyzed_query)
{tag}
ORDER BY
    MATCH(f.searchable_text) AGAINST(:analyzed_query) DESC,
    f.memory_artifact_id,
    f.entry_id,
    f.entry_version_id
LIMIT :candidate_limit
"""

_HYBRID_VECTOR_BRANCH = """
SELECT
    CAST('vector' AS CHAR(16)) AS channel,
    m.memory_artifact_id,
    m.head_revision,
    m.entry_id,
    m.entry_version_id,
    v.text,
    CAST(NULL AS DECIMAL(65, 30)) AS relevance,
    l2_distance(m.embedding, :query_vector) AS distance
FROM pc_memory_vector_entries AS m
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = m.scope_id
 AND v.memory_artifact_id = m.memory_artifact_id
 AND v.entry_version_id = m.entry_version_id
WHERE m.scope_id = :scope_id
  AND m.memory_artifact_id IN :memory_artifact_ids
{tag}
ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
LIMIT :candidate_limit
"""

_HYBRID_UNION = """
SELECT * FROM (
{fts}
) AS fts_candidates
UNION ALL
SELECT * FROM (
{vector}
) AS vector_candidates
"""


class SeekDBMemoryIndex:
    """Compose the native seekdb indexes and fuse both candidate sets in one SQL."""

    def __init__(self, fts: OceanBaseMemoryFTSIndex, vector: OceanBaseMemoryVectorIndex) -> None:
        self._fts = fts
        self._vector = vector
        self._profile = vector.profile
        self.capabilities = MemoryCapabilities(
            fts=True,
            vector=True,
            hybrid=True,
            embedding_profile=vector.profile,
            tag_filter=True,
        )
        self.tables: tuple[Table, ...] = fts.tables + vector.tables
        self._hybrid_sql = _build_hybrid_statement(text, vector.profile.dimension, tagged=False)
        self._hybrid_tagged_sql = _build_hybrid_statement(text, vector.profile.dimension, tagged=True)

    async def initialize(self, connection: AsyncConnection, /) -> None:
        await self._fts.initialize(connection)
        await self._vector.initialize(connection)

    async def replace(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._fts.replace(connection, scope_id, memory_ref, projections)
        await self._vector.replace(connection, scope_id, memory_ref, projections)

    async def delete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        entry_ids: tuple[str, ...],
        /,
    ) -> None:
        await self._fts.delete(connection, scope_id, memory_ref, entry_ids)
        await self._vector.delete(connection, scope_id, memory_ref, entry_ids)

    async def upsert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._fts.upsert(connection, scope_id, memory_ref, projections)
        await self._vector.upsert(connection, scope_id, memory_ref, projections)

    async def search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
        /,
    ) -> MemorySearchChannels:
        if request.mode == "fts":
            return await self._fts.search(connection, scope_id, request)
        if request.mode == "vector":
            return await self._vector.search(connection, scope_id, request)
        if request.mode != "hybrid":
            return MemorySearchChannels()
        if request.embedding_profile != self._profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self._vector.vector_complete(connection, scope_id, request.memories, self._profile):
            raise CapabilityNotSupportedError("vector")

        statement = self._hybrid_tagged_sql if request.tag_filter is not None else self._hybrid_sql
        parameters: dict[str, Any] = {
            "scope_id": scope_id,
            "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
            "analyzed_query": request.analyzed_query,
            "query_vector": validate_embedding(
                request.query_vector,
                dimension=self._profile.dimension,
            ),
            "candidate_limit": request.candidate_limit,
        }
        tag_parameters = memory_tag_parameters(request.tag_filter)
        if tag_parameters:
            parameters.update({
                "fts_tag_keys": tag_parameters["tag_keys"],
                "fts_tag_hashes": tag_parameters["tag_hashes"],
                "fts_tag_minimum": tag_parameters["tag_minimum"],
                "vector_tag_keys": tag_parameters["tag_keys"],
                "vector_tag_hashes": tag_parameters["tag_hashes"],
                "vector_tag_minimum": tag_parameters["tag_minimum"],
            })
        rows = (await connection.execute(statement, parameters)).mappings().all()
        return _split_channels(rows, request.memories)

    async def vector_complete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memories: tuple[ArtifactRef, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        return await self._vector.vector_complete(connection, scope_id, memories, profile)

    async def hydrate(
        self,
        connection: AsyncConnection,
        scope_id: str,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> tuple[MemoryProjection, ...]:
        return await self._vector.hydrate(connection, scope_id, projections)


def _tag_fragment(alias: str, prefix: str) -> str:
    return (
        memory_tag_sql(alias)
        .replace(":tag_hashes", f":{prefix}_tag_hashes")
        .replace(":tag_keys", f":{prefix}_tag_keys")
        .replace(":tag_minimum", f":{prefix}_tag_minimum")
    )


def _build_hybrid_statement(text_factory: Any, dimension: int, *, tagged: bool) -> Any:
    fts_tag = _tag_fragment("f", "fts") if tagged else ""
    vector_tag = _tag_fragment("m", "vector") if tagged else ""
    sql = _HYBRID_UNION.format(
        fts=_HYBRID_FTS_BRANCH.format(tag=fts_tag),
        vector=_HYBRID_VECTOR_BRANCH.format(tag=vector_tag),
    )
    statement = text_factory(sql).bindparams(
        bindparam("memory_artifact_ids", expanding=True),
        bindparam("query_vector", type_=VECTOR(dimension)),
    )
    if tagged:
        statement = statement.bindparams(
            bindparam("fts_tag_keys", expanding=True),
            bindparam("fts_tag_hashes", expanding=True),
            bindparam("vector_tag_keys", expanding=True),
            bindparam("vector_tag_hashes", expanding=True),
        )
    return statement


def _split_channels(
    rows: list[Mapping[Any, Any]],
    memories: tuple[ArtifactRef, ...],
) -> MemorySearchChannels:
    fts_rows = [row for row in rows if str(row["channel"]) == "fts"]
    vector_rows = [row for row in rows if str(row["channel"]) == "vector"]
    # The per-branch LIMIT selects the candidates; re-establish the documented
    # per-channel order after the UNION so ranks do not depend on row delivery order.
    fts_rows.sort(
        key=lambda row: (
            -float(row["relevance"]),
            str(row["memory_artifact_id"]),
            str(row["entry_id"]),
            str(row["entry_version_id"]),
        )
    )
    vector_rows.sort(
        key=lambda row: (
            float(row["distance"]),
            str(row["memory_artifact_id"]),
            str(row["entry_id"]),
            str(row["entry_version_id"]),
        )
    )
    return MemorySearchChannels(
        fts=memory_channel_hits(fts_rows, memories),
        vector=memory_channel_hits(vector_rows, memories),
    )


__all__ = ["SeekDBMemoryIndex"]
