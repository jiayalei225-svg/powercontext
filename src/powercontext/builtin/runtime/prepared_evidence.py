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

"""Select literal, query-relevant spans from recalled Memory entries.

The selector is deliberately lexical and offline: retrieval has already chosen the
candidate entries, and this module only decides which character ranges to deliver.
Spans always come from the original entry text and are budgeted by the exact
UTF-8 size of the rendered evidence envelope.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_BEGIN_MARKER = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END_MARKER = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"
_MAX_FRAGMENTS = 3
_FIRST_SEGMENT_WEIGHT = 0.1
_QUERY_BIGRAM_BONUS = 0.3
_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+")
_SENTENCE_END_RE = re.compile(
    r"""[.!?]+["'\N{RIGHT DOUBLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK})\]]*(?=\s|$)"""
)
_WORD_BEFORE_RE = re.compile(r"([A-Za-z][A-Za-z.]*)$")
_STOPWORDS = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "hers",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "may",
    "me",
    "might",
    "more",
    "most",
    "must",
    "my",
    "no",
    "nor",
    "not",
    "of",
    "on",
    "or",
    "our",
    "out",
    "over",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "under",
    "up",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
])
_ABBREVIATIONS = frozenset({
    "al",
    "approx",
    "ca",
    "cf",
    "dr",
    "e.g",
    "eq",
    "et al",
    "fig",
    "i.e",
    "mr",
    "ms",
    "no",
    "prof",
    "ref",
    "st",
    "vs",
})


@dataclass(frozen=True)
class EvidenceCandidate:
    """One exact Memory entry that may contribute a literal fragment."""

    scope_id: str
    memory_ref: ArtifactRef
    entry_id: str
    entry_version_id: str
    text: str


@dataclass(frozen=True)
class EvidenceFragment:
    """One selected character range together with the entry that owns it."""

    candidate: EvidenceCandidate
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Segment:
    start: int
    end: int
    terms: tuple[str, ...]
    score: float = 0.0


@dataclass(frozen=True)
class _Window:
    candidate_index: int
    start: int
    end: int
    text: str
    score: float


def select_evidence_fragments(
    query: str,
    candidates: Sequence[EvidenceCandidate],
    *,
    max_bytes: int,
) -> tuple[EvidenceFragment, ...]:
    """Select up to three non-overlapping literal fragments within ``max_bytes``.

    The primary window is the highest-scoring contiguous range of sentences. A
    secondary window is added only when it fits the remaining exact budget and
    does not overlap an earlier fragment, which preserves single-document
    coverage while allowing evidence spread across distinct entries.
    """

    unique = _deduplicate(candidates)
    if not unique:
        return ()
    windows = _windows(query, unique, max_bytes=max_bytes)
    selected: list[_Window] = []
    for window in windows:
        if any(_overlaps(window, chosen) for chosen in selected):
            continue
        if selected and window.score <= 0:
            continue
        fragments = _fragments(unique, (*selected, window))
        if len(render_evidence(fragments).encode("utf-8")) > max_bytes:
            continue
        selected.append(window)
        if len(selected) >= _MAX_FRAGMENTS:
            break
    if not selected:
        return ()
    ordered = sorted(selected, key=lambda window: (window.candidate_index, window.start, window.end))
    return _fragments(unique, ordered)


def render_evidence(fragments: Sequence[EvidenceFragment]) -> str:
    """Render the exact evidence envelope measured by the byte budget."""

    envelope = {
        "trust": "untrusted_history",
        "items": [
            {
                "citation": evidence_citation(fragment),
                "content": fragment.text,
                "start": fragment.start,
                "end": fragment.end,
            }
            for fragment in fragments
        ],
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return "\n\n".join((TRUST_POLICY, f"{_BEGIN_MARKER}\n{encoded}\n{_END_MARKER}"))


def evidence_citation(fragment: EvidenceFragment) -> dict[str, object]:
    """Render one fragment's exact citation without losing its Scope identity."""

    candidate = fragment.candidate
    return {
        "scope_id": candidate.scope_id,
        "memory_ref": candidate.memory_ref.model_dump(mode="json"),
        "entry_id": candidate.entry_id,
        "entry_version_id": candidate.entry_version_id,
    }


def _deduplicate(candidates: Sequence[EvidenceCandidate]) -> tuple[EvidenceCandidate, ...]:
    seen: set[tuple[str, str, str, int, str, str]] = set()
    unique: list[EvidenceCandidate] = []
    for candidate in candidates:
        reference = candidate.memory_ref
        identity = (
            candidate.scope_id,
            reference.family,
            reference.artifact_id,
            reference.revision,
            candidate.entry_id,
            candidate.entry_version_id,
        )
        if identity in seen:
            continue
        seen.add(identity)
        if not candidate.entry_id.strip() or not candidate.entry_version_id.strip() or not candidate.text.strip():
            continue
        unique.append(candidate)
    return tuple(unique)


def _windows(
    query: str,
    candidates: tuple[EvidenceCandidate, ...],
    *,
    max_bytes: int,
) -> tuple[_Window, ...]:
    segment_sets = tuple(_segments(candidate.text) for candidate in candidates)
    scored = _score_segments(query, segment_sets)
    windows: list[_Window] = []
    minimum_envelope = len(render_evidence(()).encode("utf-8"))
    for candidate_index, segments in enumerate(scored):
        text = candidates[candidate_index].text
        for first in range(len(segments)):
            for last in range(first, len(segments)):
                start = segments[first].start
                end = segments[last].end
                fragment_text = text[start:end]
                if not fragment_text.strip():
                    continue
                if len(fragment_text.encode("utf-8")) + minimum_envelope > max_bytes:
                    break
                score = _window_score(segments[first : last + 1])
                windows.append(
                    _Window(
                        candidate_index=candidate_index,
                        start=start,
                        end=end,
                        text=fragment_text,
                        score=score,
                    )
                )
    windows.sort(
        key=lambda window: (
            -window.score,
            len(window.text.encode("utf-8")),
            window.candidate_index,
            window.start,
        )
    )
    return tuple(windows)


def _window_score(segments: Sequence[_Segment]) -> float:
    """Prefer windows with both relevant depth and at least one strong sentence.

    A plain score sum lets many weakly matching sentences outweigh one precise
    sentence, while a bare maximum ignores evidence split over adjacent
    sentences. The square root keeps a long window from winning on length alone,
    and the maximum term keeps precision.
    """

    scores = [max(0.0, segment.score) for segment in segments]
    return math.sqrt(sum(scores)) + 0.75 * max(scores, default=0.0)


def _segments(text: str) -> tuple[_Segment, ...]:
    return tuple(_Segment(start=start, end=end, terms=_terms(text[start:end])) for start, end in _sentence_spans(text))


def _score_segments(
    query: str,
    segment_sets: tuple[tuple[_Segment, ...], ...],
) -> tuple[tuple[_Segment, ...], ...]:
    query_terms = _terms(query)
    query_set = frozenset(query_terms)
    query_bigrams = tuple(pairwise(query_terms))
    flat = tuple(segment for segments in segment_sets for segment in segments)
    if not flat:
        return tuple(() for _ in segment_sets)
    document_frequency: Counter[str] = Counter()
    for segment in flat:
        document_frequency.update(set(segment.terms))
    average_length = sum(len(segment.terms) for segment in flat) / len(flat) or 1.0
    idf = {
        term: math.log(1.0 + (len(flat) - frequency + 0.5) / (frequency + 0.5))
        for term, frequency in document_frequency.items()
    }
    k1 = 1.2
    b = 0.75
    scored: list[tuple[_Segment, ...]] = []
    for segments in segment_sets:
        candidate_segments: list[_Segment] = []
        for segment_index, segment in enumerate(segments):
            frequencies = Counter(segment.terms)
            normalizer = k1 * (1.0 - b + b * len(segment.terms) / average_length)
            score = sum(
                idf.get(term, 0.0) * frequency * (k1 + 1.0) / (frequency + normalizer)
                for term in query_set
                if (frequency := frequencies.get(term, 0))
            )
            present = set(segment.terms)
            score += sum(_QUERY_BIGRAM_BONUS for left, right in query_bigrams if left in present and right in present)
            # A title or opening sentence is expensive before retrieval has narrowed the
            # entry, so it competes with lower weight while staying available to a window.
            if segment_index == 0:
                score *= _FIRST_SEGMENT_WEIGHT
            candidate_segments.append(_Segment(start=segment.start, end=segment.end, terms=segment.terms, score=score))
        scored.append(tuple(candidate_segments))
    return tuple(scored)


def _sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end()
        if _is_abbreviation(text, match.start()):
            continue
        next_index = end
        while next_index < len(text) and text[next_index].isspace():
            next_index += 1
        # Only a lowercase Latin word continues the same sentence. CJK text has no case,
        # so its sentence boundaries must not depend on ``str.isupper``.
        if next_index < len(text) and text[next_index].islower():
            continue
        spans.append((start, end))
        start = end
    spans.append((start, len(text)))
    trimmed: list[tuple[int, int]] = []
    for span_start, span_end in spans:
        while span_start < span_end and text[span_start].isspace():
            span_start += 1
        while span_end > span_start and text[span_end - 1].isspace():
            span_end -= 1
        if span_start < span_end:
            trimmed.append((span_start, span_end))
    return tuple(trimmed)


def _is_abbreviation(text: str, dot_index: int) -> bool:
    match = _WORD_BEFORE_RE.search(text[: dot_index + 1])
    if match is None:
        return False
    word = match.group(1).rstrip(".").lower()
    if word in _ABBREVIATIONS:
        return True
    if len(word) == 1:
        return True
    return bool(re.fullmatch(r"(?:[a-z]\.)+[a-z]?", word + "."))


def _terms(text: str) -> tuple[str, ...]:
    return tuple(_stem(token) for token in _TOKEN_RE.findall(text.lower()) if token not in _STOPWORDS)


def _stem(token: str) -> str:
    if len(token) <= 3:
        return token
    for suffix in ("ations", "ation", "ments", "ment", "ness", "ingly", "ing", "edly", "ed", "ies", "es", "s", "ly"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            if suffix == "ies":
                return f"{token[:-3]}y"
            return token[: -len(suffix)]
    return token


def _fragments(candidates: tuple[EvidenceCandidate, ...], windows: Sequence[_Window]) -> tuple[EvidenceFragment, ...]:
    return tuple(
        EvidenceFragment(
            candidate=candidates[window.candidate_index],
            start=window.start,
            end=window.end,
            text=window.text,
        )
        for window in windows
    )


def _overlaps(left: _Window, right: _Window) -> bool:
    return left.candidate_index == right.candidate_index and left.start < right.end and right.start < left.end


__all__ = [
    "EvidenceCandidate",
    "EvidenceFragment",
    "evidence_citation",
    "render_evidence",
    "select_evidence_fragments",
]
