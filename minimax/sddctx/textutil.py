"""文本处理与本地向量化。

设计目标：

1. 不依赖外部 embedding 服务，评审在离线环境也能复现检索结果；
2. 结果**跨进程确定性**——同样的文本永远得到同样的向量，这决定了
   ``ingest`` 与 ``query`` 在不同进程里能对上同一份向量索引。

因此使用"哈希词袋 + 亚线性词频 + L2 归一化"，而不是任何带随机初始化的模型。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIM = 384

_ASCII_WORD = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")

STOPWORDS = frozenset(
    """
    the a an of to in on for and or is are be as at by with from that this it
    de la el un une des les et du
    """.split()
)


def tokenize(text: str) -> list[str]:
    """把中英混排文本切成检索词。

    - ASCII：按 ``[a-z0-9_]`` 切词并转小写；``order_filters`` 同时产出
      ``order_filters`` 与 ``order``/``filters`` 两类词，兼顾标识符与自然语言查询。
    - 中文：按字二元组切分（不需要词典，跨领域稳定）。
    """
    lowered = text.lower()
    tokens: list[str] = []

    for word in _ASCII_WORD.findall(lowered):
        if word in STOPWORDS or len(word) == 1:
            continue
        tokens.append(word)
        if "_" in word:
            parts = [p for p in word.split("_") if len(p) > 1 and p not in STOPWORDS]
            tokens.extend(parts)

    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    for run in cjk_runs:
        if len(run) == 1:
            tokens.append(run)
            continue
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))

    return tokens


def _bucket(token: str) -> tuple[int, float]:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % DIM
    sign = 1.0 if digest[4] & 1 else -1.0
    return index, sign


def embed(text: str) -> list[float]:
    """把文本编码为 ``DIM`` 维单位向量。"""
    counts = Counter(tokenize(text))
    vector = [0.0] * DIM
    if not counts:
        return vector
    for token, tf in counts.items():
        index, sign = _bucket(token)
        vector[index] += sign * (1.0 + math.log(tf))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """两个已归一化向量的余弦相似度。"""
    return sum(a * b for a, b in zip(left, right))


def keyword_overlap(query_tokens: list[str], text: str) -> float:
    """查询词在文本中的覆盖率（不做 IDF 加权，保留给简单场景）。"""
    if not query_tokens:
        return 0.0
    text_tokens = set(tokenize(text))
    if not text_tokens:
        return 0.0
    hit = sum(1 for token in set(query_tokens) if token in text_tokens)
    return hit / len(set(query_tokens))


def build_idf(documents: list[str]) -> tuple[dict[str, float], float]:
    """按语料统计 IDF，返回 (token→idf, 未见词的兜底 idf)。

    ``page_size``、``created_from`` 这类稀有标识符会得到高权重，
    ``订单``/``列表`` 这类到处出现的词权重接近 0——这正是任务与规格之间
    区分度的来源。
    """
    total = max(1, len(documents))
    df: Counter[str] = Counter()
    for document in documents:
        df.update(set(tokenize(document)))
    idf = {token: math.log((total + 1) / (count + 0.5)) for token, count in df.items()}
    fallback = math.log((total + 1) / 0.5)
    return idf, fallback


def weighted_keyword_score(
    query_tokens: list[str],
    text: str,
    idf: dict[str, float],
    fallback: float,
) -> float:
    """IDF 加权后的查询词覆盖率。"""
    query = set(query_tokens)
    if not query:
        return 0.0
    text_tokens = set(tokenize(text))
    if not text_tokens:
        return 0.0
    total_weight = 0.0
    hit_weight = 0.0
    for token in query:
        weight = idf.get(token, fallback)
        total_weight += weight
        if token in text_tokens:
            hit_weight += weight
    return hit_weight / total_weight if total_weight else 0.0


def spec_ids_in(text: str) -> list[str]:
    """抽取文本中出现的规格条目编号（含 ``SPEC-ORD-014.2`` 这类子编号）。"""
    return sorted(set(re.findall(r"SPEC-[A-Z]+-\d{3}(?:\.\d+)?", text)))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
