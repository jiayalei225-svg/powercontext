"""Search orchestration: memory-derived defaults, seekdb hybrid retrieval."""

from __future__ import annotations

import re

from . import memory, store

_STOPWORDS = {
    "的", "了", "和", "与", "在", "是", "有", "我", "想", "找", "关于", "如何", "怎么", "哪些",
    "什么", "一下", "帮我", "请", "这", "那", "篇", "文章", "论文", "研究", "有没有", "能不能",
    "为什么", "干什么", "怎么样", "方法", "the", "a", "an", "of", "for", "and", "to", "in",
    "on", "how", "what", "which", "paper", "papers",
}
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")
_KEEP_POS = ("n", "nz", "ng", "nr", "ns", "nt", "nrt", "vn", "v", "an", "a", "eng")
# jieba sometimes tags a function-word span ("比纯") as a noun; reject any
# candidate built mostly from these characters.
_FUNCTION_CHARS = set("比和与为的了是在有就都也会对把被让从到而及或把着过吗呢吧啊")


def _jieba():
    import logging

    import jieba

    jieba.setLogLevel(logging.ERROR)
    return jieba


def keyword_candidates(query: str) -> list[str]:
    """Content words in the query, best guess first."""
    out: list[str] = []
    try:
        jieba = _jieba()
        import jieba.analyse

        for tag in jieba.analyse.extract_tags(query, topK=5, allowPOS=_KEEP_POS):
            if tag not in _STOPWORDS and not (set(tag) & _FUNCTION_CHARS) and tag not in out:
                out.append(tag)
        tokens = jieba.lcut(query)
    except Exception:
        tokens = query.split()

    for token in sorted(tokens, key=len, reverse=True):
        if len(token) >= 2 and re.search(r"[\u4e00-\u9fff]", token) and token not in _STOPWORDS and token not in out:
            out.append(token)
    for word in _ASCII_WORD.findall(query):
        if word.lower() not in _STOPWORDS and word not in out:
            out.append(word)
    return out


def extract_keyword(query: str) -> str | None:
    """Pick one literal term for the full-text half of the hybrid query.

    The full-text branch is a substring match, so a generic word like "为什么"
    adds noise instead of signal. Among the content words we prefer the rarest
    one in the current corpus: it is the most discriminating.
    """
    candidates = keyword_candidates(query)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    scored = []
    for candidate in candidates[:3]:
        hits = store.count_matches(candidate)
        scored.append((hits == 0, hits, candidate))
    scored.sort()
    return scored[0][2]


def _merge(prefs: dict, request: dict) -> tuple[dict, dict, list[str]]:
    """Return (filters, applied_from_memory, notes)."""
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

    if filters["year_from"] is None and prefs.get("default_year_from"):
        filters["year_from"] = int(prefs["default_year_from"])
        applied["default_year_from"] = filters["year_from"]
        notes.append(f"按记忆默认只看 {filters['year_from']} 年以后的文献")

    if not filters["venues"] and prefs.get("default_venues"):
        filters["venues"] = list(prefs["default_venues"])
        applied["default_venues"] = filters["venues"]
        notes.append("按记忆优先限定在常读会议/期刊：" + "、".join(filters["venues"]))

    if filters["has_code"] is None and prefs.get("require_code"):
        filters["has_code"] = True
        applied["require_code"] = True
        notes.append("按记忆排除了没有开源代码的论文")

    if not filters["field"] and prefs.get("default_field"):
        filters["field"] = prefs["default_field"]
        applied["default_field"] = filters["field"]
        notes.append(f"按记忆锁定领域：{filters['field']}")

    return filters, applied, notes


def _where(filters: dict) -> dict | None:
    where: dict = {}
    if filters.get("year_from"):
        where["year"] = {"$gte": int(filters["year_from"])}
    if filters.get("year_to"):
        existing = where.get("year", {})
        existing["$lte"] = int(filters["year_to"])
        where["year"] = existing
    if filters.get("venues"):
        where["venue"] = {"$in": filters["venues"]}
    if filters.get("field"):
        where["field"] = filters["field"]
    if filters.get("paper_id"):
        where["paper_id"] = filters["paper_id"]
    if filters.get("has_code"):
        where["has_code"] = 1
    return where or None


def run(query: str, request: dict, limit: int = 12) -> dict:
    prefs = {}
    memory_ok = memory.available()
    if memory_ok:
        try:
            prefs = memory.load_preferences()
        except memory.MemoryError:
            memory_ok = False

    filters, applied, notes = _merge(prefs, request)
    where = _where(filters)
    keyword = extract_keyword(query)

    hits = store.hybrid_search(query, keyword, where, limit)
    if not hits:
        hits = store.vector_only(query, where, limit)

    results = []
    for hit in hits:
        meta = hit["metadata"]
        results.append(
            {
                "chunk_id": hit["chunk_id"],
                "text": hit["text"],
                "page": meta.get("page"),
                "paper_id": meta.get("paper_id"),
                "title": meta.get("title"),
                "year": meta.get("year") or None,
                "venue": meta.get("venue"),
                "field": meta.get("field"),
                "source": meta.get("source"),
                "has_code": bool(meta.get("has_code")),
                "score": hit.get("score"),
            }
        )

    if memory_ok:
        try:
            memory.log_search(query, applied or {"raw": filters}, len(results))
        except memory.MemoryError:
            memory_ok = False

    return {
        "query": query,
        "keyword": keyword,
        "results": results,
        "filters": filters,
        "applied_from_memory": applied,
        "memory_notes": notes,
        "memory_connected": memory_ok,
        "total": len(results),
    }
