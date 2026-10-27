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

from __future__ import annotations

import json
from typing import cast

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryHit
from powercontext.builtin.runtime import PrepareContextRequest
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuilder,
    PreparedMemoryCandidates,
)

MEMORY_REF = ArtifactRef(family="memory", artifact_id="memory", revision=3)
TEXT = (
    "Seasonal rainfall patterns were stable across the record. "
    "The telescope array resolves faint galaxies in the deep field."
)


def _hit(entry_id: str, text: str = TEXT) -> MemoryHit:
    return MemoryHit(
        memory_ref=MEMORY_REF,
        entry_id=entry_id,
        entry_version_id=f"{entry_id}-v1",
        text=text,
        score=1.0,
        matched_by=("fts",),
    )


def _item_payloads(content: str) -> list[dict[str, object]]:
    document = cast(dict[str, object], json.loads(content.splitlines()[-2]))
    assert document["trust"] == "untrusted_history"
    return cast(list[dict[str, object]], document["items"])


def test_evidence_selection_defaults_off_and_requires_a_json_boolean() -> None:
    assert PrepareContextRequest(query="telescope").evidence_selection is False
    for value in ("true", 1, None):
        with pytest.raises(ValidationError):
            PrepareContextRequest.model_validate({"query": "telescope", "evidence_selection": value})


def test_evidence_fragments_preserve_literal_text_citations_and_origins() -> None:
    candidates = tuple(
        PreparedMemoryCandidates(scope_id=scope_id, memory_ref=MEMORY_REF, hits=(_hit(f"entry-{scope_id}"),))
        for scope_id in ("scope-a", "scope-b")
    )
    request = PrepareContextRequest(query="telescope faint galaxies", max_bytes=1400, evidence_selection=True)

    build = PreparedContextBuilder().build_scopes_result(
        request=request,
        current_scope_id="scope-a",
        memory_candidates=candidates,
    )

    assert build.context.status == "ready"
    assert build.context.content is not None
    assert build.context.content_bytes == len(build.context.content.encode("utf-8"))
    assert build.context.content_bytes <= request.max_bytes
    assert len(build.fragments) == len(build.origins) > 0
    payloads = _item_payloads(build.context.content)
    assert len(payloads) == len(build.fragments)
    for fragment, origin, payload in zip(build.fragments, build.origins, payloads, strict=True):
        assert isinstance(origin, MemoryEntryAddress)
        assert origin == fragment.address
        assert 0 <= fragment.start < fragment.end <= len(TEXT)
        assert fragment.text == TEXT[fragment.start : fragment.end]
        assert payload["content"] == fragment.text
        assert (payload["start"], payload["end"]) == (fragment.start, fragment.end)
        assert payload["citation"] == {
            "scope_id": origin.memory.scope_id,
            "memory_ref": MEMORY_REF.model_dump(mode="json"),
            "entry_id": fragment.address.entry_id,
            "entry_version_id": fragment.address.entry_version_id,
        }


def test_evidence_selection_finds_late_query_evidence() -> None:
    late = "The buried constraint is that the telescope must stay below ten kelvin."
    text = (
        "A general overview of archived measurements is provided here. "
        + "Routine calibration notes repeat the same schedule every season. " * 4
        + late
    )
    request = PrepareContextRequest(query="telescope kelvin constraint", max_bytes=1400, evidence_selection=True)

    build = PreparedContextBuilder().build_scopes_result(
        request=request,
        current_scope_id="scope",
        memory_candidates=(PreparedMemoryCandidates("scope", MEMORY_REF, (_hit("entry", text),)),),
    )

    late_start = text.index(late)
    assert any(fragment.start <= late_start and fragment.end >= late_start + len(late) for fragment in build.fragments)


def test_evidence_selection_off_keeps_full_entry_text() -> None:
    candidates = (PreparedMemoryCandidates("scope", MEMORY_REF, (_hit("entry"),)),)
    baseline_request = PrepareContextRequest(query="telescope faint galaxies", max_bytes=1400)
    baseline = PreparedContextBuilder().build_scopes_result(
        request=baseline_request,
        current_scope_id="scope",
        memory_candidates=candidates,
    )
    selected = PreparedContextBuilder().build_scopes_result(
        request=baseline_request.model_copy(update={"evidence_selection": True}),
        current_scope_id="scope",
        memory_candidates=candidates,
    )

    assert baseline.fragments == ()
    assert selected.fragments
    assert baseline.context.content is not None
    payload = _item_payloads(baseline.context.content)[0]
    assert payload["content"] == TEXT
    assert "start" not in payload


def test_evidence_selection_returns_empty_context_without_candidates() -> None:
    build = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="telescope", max_bytes=1400, evidence_selection=True),
        current_scope_id="scope",
    )

    assert build.context.status == "empty"
    assert build.context.content is None
    assert build.context.content_bytes == 0
    assert build.fragments == ()
    assert build.origins == ()
