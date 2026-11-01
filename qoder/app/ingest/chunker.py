"""Structure-aware chunking.

The citation contract needs ``section`` and ``page`` to stay meaningful, so
markdown is split on heading boundaries before any size-based windowing, and
PDF text is never merged across pages. Long paragraphs fall back to a sliding
window so no chunk exceeds the embedding budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 520
OVERLAP_CHARS = 80

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class Chunk:
    chunk_id: str
    text: str
    section: str
    page: int
    index: int


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]


def _split_long(paragraph: str, limit: int) -> list[str]:
    sentences = re.split(r"(?<=[。！？!?；;])", paragraph)
    pieces: list[str] = []
    buf = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > limit:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.extend(sentence[i : i + limit] for i in range(0, len(sentence), limit))
            continue
        if len(buf) + len(sentence) > limit:
            pieces.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        pieces.append(buf)
    return pieces


def _windows(paragraphs: list[str], limit: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for paragraph in paragraphs:
        pieces = _split_long(paragraph, limit) if len(paragraph) > limit else [paragraph]
        for piece in pieces:
            if not buf:
                buf = piece
            elif len(buf) + len(piece) + 1 <= limit:
                buf = f"{buf}\n{piece}"
            else:
                chunks.append(buf)
                tail = buf[-overlap:] if overlap else ""
                buf = f"{tail}\n{piece}" if tail else piece
    if buf:
        chunks.append(buf)
    return chunks


def chunk_markdown(doc_id: str, text: str) -> list[Chunk]:
    """Split by heading path first, then by size inside each section."""
    sections: list[tuple[str, list[str]]] = []
    stack: list[str] = []
    current: list[str] = []
    current_path = "引言"
    started = False

    def flush() -> None:
        nonlocal current
        body = "\n\n".join(current).strip()
        lines = [line for line in body.splitlines() if line.strip()]
        # A parent heading followed immediately by a child heading would
        # otherwise become a chunk containing only "# 第三章 ..." — high
        # lexical score, near-zero information.
        if len(lines) == 1 and _HEADING.match(lines[0].strip()):
            current = []
            return
        if body:
            sections.append((current_path, _paragraphs(body)))
        current = []

    for line in text.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            flush()
            level = len(match.group(1))
            stack = stack[: level - 1] + [match.group(2).strip()]
            current_path = " / ".join(stack)
            # Keep the heading line in the body: heading words are often the
            # best full-text signal ("正则化", "特征值分解") and the UI shows the
            # same text the user wrote.
            current = [line.strip()]
            started = True
        else:
            current.append(line)
    flush()

    if not sections and text.strip():
        sections = [("正文", _paragraphs(text))]

    chunks: list[Chunk] = []
    for section, paragraphs in sections:
        heading = section.split(" / ")[-1]
        for piece in _windows(paragraphs, MAX_CHARS, OVERLAP_CHARS):
            body = piece if heading in piece[:40] else f"{heading}\n{piece}"
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}::{len(chunks):04d}",
                    text=body.strip(),
                    section=section,
                    page=0,
                    index=len(chunks),
                )
            )
    return chunks


def chunk_plain(doc_id: str, text: str, *, page: int, section: str, start_index: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for piece in _windows(_paragraphs(text), MAX_CHARS, OVERLAP_CHARS):
        index = start_index + len(chunks)
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}::{index:04d}",
                text=piece.strip(),
                section=section,
                page=page,
                index=index,
            )
        )
    return chunks
