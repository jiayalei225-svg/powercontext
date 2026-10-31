"""Turn uploaded documents into page-anchored chunks.

Every chunk keeps the page it came from so a search hit can point back to an
exact location instead of a vague "somewhere in this PDF".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

CHUNK_SIZE = 360
CHUNK_OVERLAP = 60

_SENTENCE_END = re.compile(r"(?<=[。！？；.!?;])\s*")
_YEAR = re.compile(r"(19|20)\d{2}")
_WS = re.compile(r"[ \t\u3000]+")
_BLANK = re.compile(r"\n{3,}")


@dataclass
class Page:
    number: int
    text: str


@dataclass
class ParsedDoc:
    title: str
    pages: list[Page]
    metadata: dict = field(default_factory=dict)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    page: int
    index: int


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = _WS.sub(" ", text)
    text = _BLANK.sub("\n\n", text)
    return text.strip()


def _pdf_pages(path: Path) -> tuple[list[Page], dict]:
    import fitz

    pages: list[Page] = []
    with fitz.open(path) as doc:
        meta = dict(doc.metadata or {})
        for i, page in enumerate(doc, start=1):
            text = _clean(page.get_text("text"))
            if text:
                pages.append(Page(number=i, text=text))
    return pages, meta


def _text_pages(path: Path) -> list[Page]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return [Page(number=1, text=_clean(raw))]


def parse_document(path: Path) -> ParsedDoc:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages, meta = _pdf_pages(path)
        title = (meta.get("title") or "").strip()
    else:
        pages, meta = _text_pages(path), {}
        title = ""
    if not title:
        title = path.stem.replace("_", " ").strip()
    return ParsedDoc(title=title, pages=pages, metadata=meta)


def guess_year(title: str, text: str) -> int | None:
    for source in (title, text[:400]):
        match = _YEAR.search(source)
        if match:
            return int(match.group(0))
    return None


def split_pages(pages: list[Page], paper_id: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    cursor = 0
    for page in pages:
        text = page.text
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            if end < len(text):
                window = text[start:end]
                cut = max((m.end() for m in _SENTENCE_END.finditer(window)), default=0)
                if cut > CHUNK_SIZE // 2:
                    end = start + cut
            piece = text[start:end].strip()
            if len(piece) >= 30:
                chunks.append(Chunk(chunk_id=f"{paper_id}:{cursor:05d}", text=piece, page=page.number, index=cursor))
                cursor += 1
            if end >= len(text):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def paper_id_for(path: Path, title: str) -> str:
    digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    return f"pp_{digest}"
