"""Three-way retrieval over one seekdb collection.

A query can use any of:

* vector search   - semantic similarity from the BGE embedding
* full-text search - literal term match through seekdb's full-text index
* metadata filter  - subject / document / section, applied to both branches

``hybrid`` fuses the two ranked lists with a weighted Reciprocal Rank Fusion.
Weights live in ``config.py`` so the fusion is reproducible and inspectable,
and every call writes one trace row with the input, filters and hit summary.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..config import settings
from ..seekdb import db, repo
from ..trace.models import LAYER_SEEKDB, TraceEvent

log = logging.getLogger(__name__)

RRF_K = 60
MODES = ("hybrid", "vector", "fulltext")

_STOPWORDS = {
    "的", "了", "和", "与", "在", "是", "有", "我", "想", "找", "关于", "如何", "怎么",
    "哪些", "什么", "一下", "帮我", "请", "这", "那", "为什么", "怎么样", "可以", "需要",
    "解释", "介绍", "讲讲", "说说", "一个", "以及", "还有", "the", "a", "an", "of", "for",
    "and", "to", "in", "on", "how", "what", "which", "is", "are", "上次", "这次", "之前",
    "上错", "化上", "错在", "哪里", "区别", "不同",
}
_KEEP_POS = ("n", "nz", "ng", "nr", "ns", "nt", "nrt", "vn", "v", "an", "a", "eng")
_FUNCTION_CHARS = set("的了和与在是有我你他她它想找上下里哪这那么呢吧啊就都也会对把被让从到而及或着吗")
_ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")

# jieba's general dictionary splits domain compounds ("正则化" -> "正则/化上"),
# which poisons literal search. Teaching it the course vocabulary keeps keywords
# aligned with how the documents are actually written.
_DOMAIN_TERMS = (
    "正则化", "过拟合", "欠拟合", "特征值", "特征向量", "奇异值分解", "梯度下降",
    "随机梯度下降", "小批量", "交叉验证", "条件数", "中心化", "协方差矩阵",
    "权重衰减", "稀疏解", "偏差", "方差", "学习率", "动量", "早停", "数据增强",
    "损失函数", "经验风险", "零空间", "线性相关", "线性无关", "对角化",
    "正定矩阵", "低秩近似", "主成分分析", "核函数", "支持向量", "集成学习",
    "批量梯度下降", "精确率", "召回率", "准确率", "混淆矩阵", "时间序列",
    "牛顿法", "牛顿迭代", "特征分解", "矩阵分解", "奇异值", "转置", "投影",
)
_terms_loaded = False


def _load_terms() -> None:
    global _terms_loaded
    if _terms_loaded:
        return
    try:
        import jieba

        jieba.setLogLevel(logging.ERROR)
        for term in _DOMAIN_TERMS:
            jieba.add_word(term)
    except Exception:
        pass
    _terms_loaded = True


def _is_candidate(term: str) -> bool:
    if not term or term in _STOPWORDS or len(term) < 2:
        return False
    if term[0] in _FUNCTION_CHARS or term[-1] in _FUNCTION_CHARS:
        return False
    return any("\u4e00" <= char <= "\u9fff" for char in term) or _ASCII_WORD.fullmatch(term) is not None


def keyword_candidates(query: str, limit: int = 3) -> list[str]:
    """Content words used by the literal full-text branch.

    Longer compounds are preferred ("过拟合" over "拟合") because the full-text
    branch is a literal match and the specific term is the better filter.
    """
    _load_terms()
    tags: list[str] = []
    tokens: list[str] = []
    try:
        import jieba
        import jieba.analyse

        for term in jieba.analyse.extract_tags(query, topK=limit + 4, allowPOS=_KEEP_POS):
            if _is_candidate(term):
                tags.append(term)
        tokens = [token for token in jieba.lcut(query) if _is_candidate(token)]
    except Exception:
        tokens = [
            token
            for token in re.split(r"[\s,，。？?！!；;：:、]+", query)
            if _is_candidate(token)
        ]

    ranked = sorted(set(tokens) | set(tags), key=lambda term: (-len(term), term))
    pruned: list[str] = []
    for term in ranked:
        if any(term in longer and term != longer for longer in pruned):
            continue
        pruned.append(term)
    for word in _ASCII_WORD.findall(query):
        if _is_candidate(word) and word.lower() not in {item.lower() for item in pruned}:
            pruned.append(word)
    return pruned[:limit]


def _where(subject: str | None, doc_id: str | None, section: str | None) -> dict | None:
    where: dict[str, Any] = {}
    if subject:
        where["subject"] = subject
    if doc_id:
        where["doc_id"] = doc_id
    if section:
        where["section"] = section
    return where or None


def _unwrap(result: dict) -> tuple[list[str], list[str], list[dict], list[float]]:
    return (
        (result.get("ids") or [[]])[0],
        (result.get("documents") or [[]])[0],
        (result.get("metadatas") or [[]])[0],
        (result.get("distances") or [[]])[0],
    )


def _to_hit(chunk_id: str, text: str, meta: dict, raw: float, matched_by: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "doc_id": meta.get("doc_id"),
        "doc_title": meta.get("doc_title"),
        "subject": meta.get("subject"),
        "section": meta.get("section"),
        "page": int(meta.get("page") or 0),
        "source_path": meta.get("source_path"),
        "chunk_index": int(meta.get("chunk_index") or 0),
        "raw_score": raw,
        "matched_by": [matched_by],
    }


def vector_hits(query: str, where: dict | None, limit: int) -> list[dict]:
    result = db.collection().query(
        query_texts=[query],
        n_results=limit,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    ids, documents, metadatas, distances = _unwrap(result)
    return [
        _to_hit(chunk_id, documents[i], metadatas[i], float(distances[i]), "vector")
        for i, chunk_id in enumerate(ids)
    ]


def fulltext_hits(keywords: list[str], where: dict | None, limit: int) -> list[dict]:
    """One literal query per keyword, merged in keyword order."""
    if not keywords:
        return []
    merged: dict[str, dict] = {}
    for keyword in keywords:
        query: dict[str, Any] = {
            "where_document": {"$contains": keyword},
            "n_results": limit,
        }
        if where:
            query["where"] = where
        result = db.collection().hybrid_search(
            query=query,
            knn=None,
            rank={"rrf": {}},
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )
        ids, documents, metadatas, distances = _unwrap(result)
        for i, chunk_id in enumerate(ids):
            if chunk_id in merged:
                if "fulltext" not in merged[chunk_id]["matched_by"]:
                    merged[chunk_id]["matched_by"].append("fulltext")
                continue
            hit = _to_hit(chunk_id, documents[i], metadatas[i], float(distances[i]), "fulltext")
            hit["matched_keyword"] = keyword
            merged[chunk_id] = hit
    return list(merged.values())


def _fuse(vector: list[dict], fulltext: list[dict], limit: int) -> list[dict]:
    wv = max(settings.hybrid_vector_weight, 0.0)
    wf = max(settings.hybrid_fts_weight, 0.0)
    if wv == 0 and wf == 0:
        wv, wf = 0.6, 0.4

    fused: dict[str, dict] = {}
    for rank, hit in enumerate(vector, start=1):
        entry = fused.setdefault(hit["chunk_id"], dict(hit))
        entry["vector_rank"] = rank
    for rank, hit in enumerate(fulltext, start=1):
        entry = fused.get(hit["chunk_id"])
        if entry is None:
            entry = dict(hit)
            fused[hit["chunk_id"]] = entry
        entry["fts_rank"] = rank
        entry["matched_by"] = sorted(set(entry["matched_by"]) | set(hit["matched_by"]))
        entry.setdefault("matched_keyword", hit.get("matched_keyword"))

    for entry in fused.values():
        score = 0.0
        if "vector_rank" in entry:
            score += wv / (RRF_K + entry["vector_rank"])
        if "fts_rank" in entry:
            score += wf / (RRF_K + entry["fts_rank"])
        entry["raw_score"] = round(score, 6)

    ranked = sorted(fused.values(), key=lambda item: item["raw_score"], reverse=True)[:limit]
    return ranked


def _normalize(hits: list[dict], *, higher_is_better: bool) -> list[dict]:
    values = [float(hit["raw_score"]) for hit in hits]
    if not values:
        return hits
    low, high = min(values), max(values)
    span = high - low
    for hit in hits:
        if span == 0:
            hit["relevance"] = 1.0
        elif higher_is_better:
            hit["relevance"] = round((float(hit["raw_score"]) - low) / span, 4)
        else:
            hit["relevance"] = round((high - float(hit["raw_score"])) / span, 4)
    return hits


def _public(hit: dict) -> dict:
    return {
        "chunk_id": hit["chunk_id"],
        "text": hit["text"],
        "doc_id": hit["doc_id"],
        "doc_title": hit["doc_title"],
        "subject": hit["subject"],
        "section": hit["section"],
        "page": hit["page"],
        "source_path": hit.get("source_path"),
        "score": hit.get("raw_score"),
        "relevance": hit.get("relevance", 0.0),
        "matched_by": hit.get("matched_by", []),
        "matched_keyword": hit.get("matched_keyword"),
    }


def search(
    query: str,
    *,
    mode: str = "hybrid",
    subject: str | None = None,
    doc_id: str | None = None,
    section: str | None = None,
    top_k: int | None = None,
    session_id: str = "search",
) -> dict:
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    mode = mode if mode in MODES else "hybrid"
    limit = int(top_k or settings.hybrid_top_k)
    limit = max(1, min(limit, 30))
    where = _where(subject, doc_id, section)
    keywords = keyword_candidates(query)
    window = max(limit * 3, 12)

    notes: list[str] = []
    vector: list[dict] = []
    fulltext: list[dict] = []

    if mode in {"hybrid", "vector"}:
        try:
            vector = vector_hits(query, where, window)
        except Exception as exc:  # embedding or index failure must stay visible
            log.exception("vector branch failed")
            notes.append(f"向量检索失败：{exc}")
    if mode in {"hybrid", "fulltext"}:
        fulltext = fulltext_hits(keywords, where, window)

    if mode == "vector":
        hits = vector
        note = "仅使用向量相似度；分数为向量距离，越小越接近。"
    elif mode == "fulltext":
        hits = fulltext
        note = "仅使用关键词字面匹配；适合精确术语，召回窄于向量检索。"
    else:
        hits = _fuse(vector, fulltext, limit)
        note = (
            f"RRF 融合：向量权重 {settings.hybrid_vector_weight}、"
            f"全文权重 {settings.hybrid_fts_weight}，k={RRF_K}。"
        )

    hits = hits[:limit]
    if mode == "vector":
        _normalize(hits, higher_is_better=False)
    else:
        _normalize(hits, higher_is_better=True)

    if not hits and query:
        notes.append("没有命中任何 chunk；请先导入种子资料或上传文档。")

    payload = {
        "mode": mode,
        "keywords": keywords,
        "filters": where or {},
        "top_k": limit,
        "vector_count": len(vector),
        "fulltext_count": len(fulltext),
        "note": note,
        "hits": [
            {
                "chunk_id": hit["chunk_id"],
                "doc_id": hit["doc_id"],
                "doc_title": hit["doc_title"],
                "subject": hit["subject"],
                "section": hit["section"],
                "page": hit["page"],
                "score": hit.get("raw_score"),
                "matched_by": hit.get("matched_by"),
            }
            for hit in hits
        ],
    }
    event = TraceEvent(
        session_id=session_id,
        layer=LAYER_SEEKDB,
        operation=f"search_{mode}",
        input_text=query,
        result_count=len(hits),
        summary=f"{mode} 检索命中 {len(hits)} 条；关键词：{'、'.join(keywords) or '无'}",
        payload=payload,
    )
    repo.save_trace(event)

    return {
        "query": query,
        "mode": mode,
        "keywords": keywords,
        "filters": where or {},
        "note": note,
        "notes": notes,
        "results": [_public(hit) for hit in hits],
        "trace_id": event.trace_id,
    }
