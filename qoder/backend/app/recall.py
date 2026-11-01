"""Recall: query terms, memory defaults, hybrid lookup, snippets."""

from __future__ import annotations

import re
import time

from . import index, memory

STOPWORDS = {
    "的", "了", "和", "与", "在", "是", "有", "我", "想", "找", "关于", "如何", "怎么", "哪些",
    "什么", "一下", "帮我", "请", "这", "那", "篇", "文章", "论文", "研究", "有没有", "能不能",
    "为什么", "怎么样", "方法", "相关", "最近", "一些", "可以", "需要",
    "the", "a", "an", "of", "for", "and", "to", "in", "on", "how", "what", "which",
    "paper", "papers", "survey", "review",
}
KEEP_TAGS = ("n", "nz", "ng", "nr", "ns", "nt", "nrt", "vn", "v", "an", "a", "eng")
FUNCTION_CHARS = set("比和与为的了是在有就都也会对把被让从到而及或着过吗呢吧啊")
ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")
CJK = re.compile(r"[\u4e00-\u9fff]")


def _jieba():
    import logging

    import jieba

    jieba.setLogLevel(logging.ERROR)
    return jieba


def terms(query: str) -> list[str]:
    found: list[str] = []
    try:
        jieba = _jieba()
        import jieba.analyse

        for tag in jieba.analyse.extract_tags(query, topK=6, allowPOS=KEEP_TAGS):
            if tag in STOPWORDS or tag in found or (set(tag) & FUNCTION_CHARS):
                continue
            found.append(tag)
        pieces = jieba.lcut(query)
    except Exception:
        pieces = query.split()

    for piece in sorted(pieces, key=len, reverse=True):
        if len(piece) >= 2 and CJK.search(piece) and piece not in STOPWORDS and piece not in found:
            found.append(piece)
    for word in ASCII_TOKEN.findall(query):
        if word.lower() not in STOPWORDS and word not in found:
            found.append(word)
    return found


def literal(query: str) -> str | None:
    candidates = terms(query)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    ranked = []
    for position, candidate in enumerate(candidates[:4]):
        hits = index.literal_count(candidate)
        ranked.append((hits == 0, hits, position, candidate))
    ranked.sort()
    return ranked[0][3]


def plan(prefs: dict, request: dict, use_memory: bool = True) -> tuple[dict, dict, list[str]]:
    filters = {
        "year_from": request.get("year_from"),
        "year_to": request.get("year_to"),
        "venues": list(request.get("venues") or []),
        "field": request.get("field") or None,
        "paper_id": request.get("paper_id") or None,
        "has_code": request.get("has_code"),
    }
    applied: dict = {}
    notes: list[str] = []
    if not use_memory or not prefs:
        return filters, applied, notes

    if filters["year_from"] is None and prefs.get("year_from"):
        filters["year_from"] = int(prefs["year_from"])
        applied["year_from"] = filters["year_from"]
        notes.append(f"记忆偏好：只看 {filters['year_from']} 年以后的文献")
    if not filters["venues"] and prefs.get("venues"):
        filters["venues"] = list(prefs["venues"])
        applied["venues"] = filters["venues"]
        notes.append("记忆偏好：限定在 " + "、".join(filters["venues"]))
    if filters["has_code"] is None and prefs.get("only_with_code"):
        filters["has_code"] = True
        applied["only_with_code"] = True
        notes.append("记忆偏好：只看带开源代码的论文")
    if not filters["field"] and prefs.get("field"):
        filters["field"] = prefs["field"]
        applied["field"] = filters["field"]
        notes.append(f"记忆偏好：锁定方向 {filters['field']}")
    return filters, applied, notes


def snippet(text: str, query_terms: list[str], width: int = 240) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) <= width:
        return clean
    lowered = clean.lower()
    hit = -1
    for term in query_terms:
        found = lowered.find(term.lower())
        if found != -1 and (hit == -1 or found < hit):
            hit = found
    if hit == -1:
        return clean[:width].rstrip() + "…"
    start = max(0, hit - width // 3)
    end = min(len(clean), start + width)
    if end - start < width:
        start = max(0, end - width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(clean) else ""
    return f"{prefix}{clean[start:end].strip()}{suffix}"


def _shape(hit: dict, query_terms: list[str]) -> dict:
    meta = hit["metadata"]
    return {
        "chunk_id": hit["chunk_id"],
        "text": hit["text"],
        "snippet": snippet(hit["text"], query_terms),
        "score": hit.get("score"),
        "page": meta.get("page"),
        "paper_id": meta.get("paper_id"),
        "title": meta.get("title"),
        "year": meta.get("year") or None,
        "venue": meta.get("venue"),
        "field": meta.get("field"),
        "has_code": bool(meta.get("has_code")),
        "code_url": meta.get("code_url") or None,
        "source": meta.get("source"),
    }


def _diversify(hits: list[dict], limit: int, per_paper: int = 2) -> list[dict]:
    picked: list[dict] = []
    seen: dict[str, int] = {}
    for hit in hits:
        paper_id = (hit.get("metadata") or {}).get("paper_id") or ""
        if seen.get(paper_id, 0) >= per_paper:
            continue
        seen[paper_id] = seen.get(paper_id, 0) + 1
        picked.append(hit)
        if len(picked) >= limit:
            break
    return picked


def execute(query: str, request: dict, limit: int = 12) -> dict:
    started = time.perf_counter()
    use_memory = bool(request.get("use_memory", True))
    prefs: dict = {}
    memory_ok = False
    memory_error: str | None = None
    if use_memory and memory.enabled():
        try:
            prefs = memory.load_prefs()
            memory_ok = True
        except memory.MemoryError as exc:
            memory_error = str(exc)

    filters, applied, notes = plan(prefs, request, use_memory)
    where = index.build_where(filters)
    query_terms = terms(query)
    literal_term = literal(query)

    fetch = min(limit * 3, 50)
    hits = index.hybrid(query, literal_term, where, fetch)
    strategy = "hybrid"
    if not hits:
        hits = index.nearest(query, where, fetch)
        strategy = "vector"
    hits = _diversify(hits, limit)

    results = [_shape(hit, query_terms) for hit in hits]

    if memory_ok:
        try:
            memory.trace(query, applied or {"raw": filters}, len(results))
        except memory.MemoryError as exc:
            memory_ok = False
            memory_error = str(exc)

    elapsed = round((time.perf_counter() - started) * 1000)
    return {
        "query": query,
        "terms": query_terms,
        "literal": literal_term,
        "strategy": strategy,
        "results": results,
        "total": len(results),
        "limit": limit,
        "filters": filters,
        "applied": applied,
        "notes": notes,
        "memory_connected": memory_ok,
        "memory_error": memory_error,
        "elapsed_ms": elapsed,
    }
