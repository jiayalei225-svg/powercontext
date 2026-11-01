"""File readers for the three formats the product promises: md, txt, pdf.

PDF pages are kept separate so citations can point at a real page number.
Markdown front matter is parsed by hand to avoid a YAML dependency.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LoadedDocument:
    path: Path
    file_type: str
    meta: dict = field(default_factory=dict)
    pages: list[tuple[int, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(text for _, text in self.pages if text.strip())


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[match.end() :]


def _slug(value: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return ascii_part or hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def load(path: Path) -> LoadedDocument:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"md", "markdown"}:
        raw = _decode(path.read_bytes())
        meta, body = _parse_front_matter(raw)
        meta.setdefault("title", path.stem)
        meta.setdefault("doc_id", _slug(path.stem))
        return LoadedDocument(path=path, file_type="md", meta=meta, pages=[(0, body)])

    if suffix in {"txt", "text"}:
        raw = _decode(path.read_bytes())
        return LoadedDocument(
            path=path,
            file_type="txt",
            meta={"title": path.stem, "doc_id": _slug(path.stem)},
            pages=[(0, raw)],
        )

    if suffix == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages: list[tuple[int, str]] = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                pages.append((number, page.extract_text() or ""))
            except Exception:
                pages.append((number, ""))
        title = path.stem
        try:
            if reader.metadata and reader.metadata.title:
                title = str(reader.metadata.title).strip() or title
        except Exception:
            pass
        return LoadedDocument(
            path=path,
            file_type="pdf",
            meta={"title": title, "doc_id": _slug(path.stem)},
            pages=pages,
        )

    raise ValueError(f"unsupported file type: .{suffix} (expected md, txt or pdf)")
