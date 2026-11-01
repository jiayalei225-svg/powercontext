"""PDF intake: page text, sentence-aware chunks, header metadata."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

import pymupdf

TARGET_CHARS = 380
OVERLAP_CHARS = 70
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])")
_HEADER_META = re.compile(r"^(标题|题目|会议|期刊|年份|方向|领域|代码|仓库)\s*[:：]\s*(.+?)\s*$")
_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
_REPO = re.compile(r"(?:https?://)?(?:github\.com|gitee\.com|gitlab\.com)/[\w.\-/]+", re.I)

_VENUE_ALIASES = {
    "sigmod": "SIGMOD",
    "vldb": "VLDB",
    "icde": "ICDE",
    "kdd": "KDD",
    "www": "WWW",
    "cikm": "CIKM",
    "neurips": "NeurIPS",
    "nips": "NeurIPS",
    "icml": "ICML",
    "iclr": "ICLR",
    "acl": "ACL",
    "emnlp": "EMNLP",
    "naacl": "NAACL",
    "cvpr": "CVPR",
    "iccv": "ICCV",
    "eccv": "ECCV",
    "aaai": "AAAI",
    "ijcai": "IJCAI",
    "osdi": "OSDI",
    "sosp": "SOSP",
    "nsdi": "NSDI",
    "sigcomm": "SIGCOMM",
    "sigir": "SIGIR",
    "icse": "ICSE",
    "fse": "FSE",
    "ase": "ASE",
    "计算机学报": "计算机学报",
    "软件学报": "软件学报",
    "中国科学": "中国科学",
}


@dataclass
class Chunk:
    index: int
    page: int
    text: str


@dataclass
class PaperMeta:
    title: str
    year: int | None = None
    venue: str = "未标注"
    field: str = "未分类"
    has_code: bool = False
    code_url: str | None = None
    source: str = ""
    extra: dict = dataclass_field(default_factory=dict)


def digest(data: bytes) -> str:
    return "pd2_" + hashlib.sha1(data).hexdigest()[:14]


def read_pages(path: Path) -> list[str]:
    pages: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            text = page.get_text("text") or ""
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            pages.append(text)
    return pages


def _sentences(paragraph: str) -> list[str]:
    parts = [piece.strip() for piece in _SENTENCE_END.split(paragraph) if piece.strip()]
    long_parts: list[str] = []
    for part in parts:
        if len(part) <= TARGET_CHARS:
            long_parts.append(part)
            continue
        start = 0
        while start < len(part):
            long_parts.append(part[start : start + TARGET_CHARS])
            start += TARGET_CHARS
    return long_parts


def split_pages(pages: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    cursor = 0
    for page_no, text in enumerate(pages, start=1):
        buf = ""
        for sentence in _sentences(text):
            if buf and len(buf) + len(sentence) + 1 > TARGET_CHARS:
                chunks.append(Chunk(index=cursor, page=page_no, text=buf.strip()))
                cursor += 1
                tail = buf[-OVERLAP_CHARS:]
                if not _SENTENCE_END.search(tail) and "。" in tail:
                    tail = tail[tail.rfind("。") + 1 :]
                buf = tail.strip() + sentence
            else:
                buf = f"{buf}{sentence}" if not buf else f"{buf} {sentence}"
        if buf.strip():
            chunks.append(Chunk(index=cursor, page=page_no, text=buf.strip()))
            cursor += 1
    return [chunk for chunk in chunks if len(chunk.text) >= 40]


def _header_text(pages: list[str]) -> str:
    return "\n".join(pages[:2])[:4000]


def read_meta(pages: list[str], filename: str) -> PaperMeta:
    header = _header_text(pages)
    fields: dict[str, str] = {}
    for line in header.splitlines():
        match = _HEADER_META.match(line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip()

    title = fields.get("标题") or fields.get("题目") or ""
    if not title:
        for line in header.splitlines():
            candidate = line.strip()
            if 4 <= len(candidate) <= 120 and not _HEADER_META.match(candidate):
                title = candidate
                break
    if not title:
        title = re.sub(r"[_\-]+", " ", Path(filename).stem).strip()

    year: int | None = None
    if fields.get("年份"):
        found = _YEAR.search(fields["年份"])
        year = int(found.group(1)) if found else None
    if year is None:
        found = _YEAR.search(header)
        year = int(found.group(1)) if found else None

    venue = fields.get("会议") or fields.get("期刊") or "未标注"
    if venue == "未标注":
        lowered = header.lower()
        for alias, canonical in _VENUE_ALIASES.items():
            if alias in lowered:
                venue = canonical
                break

    field_name = fields.get("方向") or fields.get("领域") or "未分类"
    code_value = fields.get("代码") or fields.get("仓库") or ""
    repo = _REPO.search(code_value) or _REPO.search(header)
    repo_url = repo.group(0).rstrip(".,;，。；）)") if repo else None
    if repo_url and not repo_url.startswith(("http://", "https://")):
        repo_url = "https://" + repo_url
    has_code = bool(repo_url) and code_value.strip() not in {"无", "否", "none", "None"}

    return PaperMeta(
        title=title,
        year=year,
        venue=venue,
        field=field_name,
        has_code=has_code,
        code_url=repo_url,
        source=filename,
        extra={"header_fields": fields},
    )
