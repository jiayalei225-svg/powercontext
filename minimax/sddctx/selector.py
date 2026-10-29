"""上下文选择。

给定一条开发任务，从 seekdb 中检索规格、代码与测试，按相关度与结构依赖
（规格 ``code_refs`` → 代码符号；测试 docstring → 规格条目）做闭包扩展，
最后在字节预算内输出一份可追溯的开发上下文。

排序分三个来源融合，便于在输出中解释"为什么选了它"：

===========  ======  ================================================
分量          权重    说明
===========  ======  ================================================
vector        0.50    seekdb 向量检索的余弦相似度
keyword       0.25    查询词覆盖率（中文字二元 + 标识符切词）
structure     0.25    结构依赖：must 条目、被选中规格引用的代码、覆盖选中规格的测试
===========  ======  ================================================
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .textutil import build_idf, embed, sha256_text, tokenize, weighted_keyword_score

WEIGHTS = {"vector": 0.45, "keyword": 0.35, "structure": 0.20}

#: 相对得分截断：低于最高分该比例的非 must 条目视为与任务无关
RELATIVE_CUTOFF = 0.42


class StoreProtocol(Protocol):
    def search(self, kind: str, query_embedding: list[float], top_k: int) -> list[dict]: ...
    def list_kind(self, kind: str) -> list[dict]: ...
    def get_by_id(self, kind: str, item_id: str) -> dict | None: ...
    def count(self, kind: str) -> int: ...


@dataclass
class Candidate:
    metadata: dict[str, Any]
    document: str
    vector_score: float = 0.0
    keyword_score: float = 0.0
    structure_score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def item_id(self) -> str:
        return str(self.metadata.get("item_id", ""))

    @property
    def score(self) -> float:
        return round(
            WEIGHTS["vector"] * self.vector_score
            + WEIGHTS["keyword"] * self.keyword_score
            + WEIGHTS["structure"] * self.structure_score,
            4,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def task_query_text(task: dict[str, Any]) -> str:
    """把任务结构拼成检索查询串。"""
    parts = [
        str(task.get("title", "")),
        str(task.get("description", "")),
        " ".join(str(x) for x in task.get("acceptance", []) or []),
        " ".join(str(x) for x in task.get("touched_paths", []) or []),
        " ".join(str(x) for x in task.get("keywords", []) or []),
    ]
    return "\n".join(part for part in parts if part)


class ContextBuilder:
    """构造一次任务上下文。"""

    def __init__(
        self,
        store: StoreProtocol,
        state: Any = None,
        *,
        budget_bytes: int = 24_000,
        spec_top_k: int = 12,
        code_top_k: int = 10,
        test_top_k: int = 12,
    ) -> None:
        self._store = store
        self._state = state
        self.budget_bytes = budget_bytes
        self.spec_top_k = spec_top_k
        self.code_top_k = code_top_k
        self.test_top_k = test_top_k
        self._idf_cache: dict[str, tuple[dict[str, float], float]] = {}

    def build(self, task: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        query_text = task_query_text(task)
        query_vector = embed(query_text)
        query_tokens = tokenize(query_text)
        task_id = str(task.get("task_id") or "unnamed")

        # 1. 规格：向量召回 + must 条目保证入选
        spec_candidates = self._recall("spec", query_vector, query_tokens, self.spec_top_k)
        all_specs = self._store.list_kind("spec")
        must_specs = [
            self._wrap(hit, query_tokens, "spec")
            for hit in all_specs
            if str(hit.get("metadata", {}).get("priority")) == "must"
        ]
        specs = self._merge(spec_candidates, must_specs, reason="spec.priority=must")
        specs.sort(key=lambda item: item.score, reverse=True)
        top_score = specs[0].score if specs else 0.0
        selected_specs = [
            item
            for item in specs
            if str(item.metadata.get("priority")) == "must"
            or item.score >= top_score * RELATIVE_CUTOFF
        ]
        if not selected_specs:
            selected_specs = specs[:3]

        selected_spec_ids = {item.item_id for item in selected_specs}
        suite_by_spec = {
            str(hit.get("metadata", {}).get("item_id")): str(
                hit.get("metadata", {}).get("suite", "functional")
            )
            for hit in all_specs
        }
        selected_refs: set[str] = set()
        for item in selected_specs:
            for ref in str(item.metadata.get("code_refs", "")).split(","):
                if ref.strip():
                    selected_refs.add(ref.strip())

        # 2. 代码：向量召回 + 规格 code_refs 精确展开 + 任务声明路径加权
        code_candidates = self._recall("code", query_vector, query_tokens, self.code_top_k)
        touched = {str(item) for item in (task.get("touched_paths") or [])}
        for candidate in code_candidates:
            if candidate.metadata.get("path") in touched:
                candidate.structure_score = max(candidate.structure_score, 0.6)
                candidate.reasons.append("touched_path:" + str(candidate.metadata.get("path")))
        referenced: list[Candidate] = []
        for ref in sorted(selected_refs):
            hit = self._store.get_by_id("code", ref)
            if hit:
                candidate = self._wrap(hit, query_tokens, "code")
                candidate.structure_score = 1.0
                candidate.reasons.append(f"referenced_by_spec:{ref}")
                referenced.append(candidate)
        code = self._merge(code_candidates, referenced, reason="spec.code_refs")
        code.sort(key=lambda item: item.score, reverse=True)

        # 3. 测试：覆盖被选中规格的用例强制入选，其余按向量召回补齐
        test_candidates = self._recall("test", query_vector, query_tokens, self.test_top_k)
        covering: list[Candidate] = []
        for hit in self._store.list_kind("test"):
            covers = {
                c.strip()
                for c in str(hit.get("metadata", {}).get("covers", "")).split(",")
                if c.strip()
            }
            if not covers & selected_spec_ids:
                continue
            candidate = self._wrap(hit, query_tokens, "test")
            candidate.structure_score = 1.0
            candidate.reasons.append("covers:" + ",".join(sorted(covers & selected_spec_ids)))
            covering.append(candidate)
        tests = self._merge(test_candidates, covering, reason="test.covers")
        tests.sort(key=lambda item: item.score, reverse=True)

        # 4. 字节预算裁剪
        spec_payload, code_payload, test_payload, truncated = self._apply_budget(
            selected_specs, code, tests, suite_by_spec
        )

        progress = self._load_progress(task_id)

        spec_version = ""
        spec_digest = ""
        for item in selected_specs:
            version = str(item.metadata.get("spec_version") or "")
            if version:
                spec_version = max(spec_version, version)
        if selected_specs:
            spec_digest = sha256_text(
                "|".join(
                    f"{item.item_id}@{item.metadata.get('spec_version')}"
                    for item in selected_specs
                )
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "task_id": task_id,
            "generated_at": _utc_now(),
            "spec_version": spec_version,
            "spec_digest": spec_digest,
            "spec_items": spec_payload,
            "code_targets": code_payload,
            "tests": {
                "functional": [item for item in test_payload if item["suite"] == "functional"],
                "regression": [item for item in test_payload if item["suite"] == "regression"],
            },
            "progress": progress,
            "metrics": {
                "candidates": {
                    "spec": len(specs),
                    "code": len(code),
                    "test": len(tests),
                },
                "selected": {
                    "spec": len(spec_payload),
                    "code": len(code_payload),
                    "test": len(test_payload),
                },
                "bytes": sum(
                    len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
                    for item in spec_payload + code_payload + test_payload
                ),
                "truncated": truncated,
                "elapsed_ms": elapsed_ms,
            },
        }

    # ------------------------------------------------------------------ 内部

    def _idf(self, kind: str) -> tuple[dict[str, float], float]:
        """按资料种类懒加载 IDF（用该类全部单元当语料）。"""
        if kind not in self._idf_cache:
            documents = [
                (hit.get("document") or "") + " " + str((hit.get("metadata") or {}).get("title", ""))
                for hit in self._store.list_kind(kind)
            ]
            self._idf_cache[kind] = build_idf(documents) if documents else ({}, 1.0)
        return self._idf_cache[kind]

    def _recall(
        self,
        kind: str,
        query_vector: list[float],
        query_tokens: list[str],
        top_k: int,
    ) -> list[Candidate]:
        hits = self._store.search(kind, query_vector, top_k)
        return [self._wrap(hit, query_tokens, kind) for hit in hits]

    def _all(self, kind: str) -> list[dict[str, Any]]:
        return self._store.list_kind(kind)

    def _wrap(self, hit: dict[str, Any], query_tokens: list[str], kind: str = "spec") -> Candidate:
        metadata = hit.get("metadata") or {}
        document = hit.get("document") or ""
        candidate = Candidate(metadata=metadata, document=document)
        candidate.vector_score = float(hit.get("score") or 0.0)
        if query_tokens and metadata:
            idf, fallback = self._idf(kind)
            candidate.keyword_score = weighted_keyword_score(
                query_tokens, document + " " + str(metadata.get("title", "")), idf, fallback
            )
        return candidate

    def _merge(
        self, base: list[Candidate], extra: list[Candidate], *, reason: str
    ) -> list[Candidate]:
        merged: dict[str, Candidate] = {item.item_id: item for item in base}
        for item in extra:
            existing = merged.get(item.item_id)
            if existing is None:
                item.reasons.append(reason)
                merged[item.item_id] = item
            else:
                existing.structure_score = max(existing.structure_score, item.structure_score)
                for entry in item.reasons:
                    if entry not in existing.reasons:
                        existing.reasons.append(entry)
        return list(merged.values())

    @staticmethod
    def _is_regression(candidate: Candidate, suite_by_spec: dict[str, str]) -> bool:
        """测试归类完全由它覆盖的规格条目的 ``suite`` 元数据决定。"""
        covers = [
            c.strip()
            for c in str(candidate.metadata.get("covers", "")).split(",")
            if c.strip()
        ]
        if not covers:
            return True
        return all(suite_by_spec.get(code, "functional") == "regression" for code in covers)

    def _apply_budget(
        self,
        specs: list[Candidate],
        code: list[Candidate],
        tests: list[Candidate],
        suite_by_spec: dict[str, str],
    ) -> tuple[list[dict], list[dict], list[dict], bool]:
        truncated = False
        spec_payload: list[dict] = []
        code_payload: list[dict] = []
        test_payload: list[dict] = []
        used = 0

        def spec_entry(candidate: Candidate) -> dict:
            refs = [
                ref.strip()
                for ref in str(candidate.metadata.get("code_refs", "")).split(",")
                if ref.strip()
            ]
            return {
                "id": candidate.item_id,
                "title": candidate.metadata.get("title", ""),
                "spec_version": candidate.metadata.get("spec_version", ""),
                "priority": candidate.metadata.get("priority", ""),
                "suite": candidate.metadata.get("suite", ""),
                "source": candidate.metadata.get("source", ""),
                "lines": f"{candidate.metadata.get('start_line')}-{candidate.metadata.get('end_line')}",
                "text": candidate.document,
                "code_refs": refs,
                "score": candidate.score,
                "match": candidate.reasons or ["vector+keyword"],
            }

        for candidate in specs:
            entry = spec_entry(candidate)
            size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            if used + size > self.budget_bytes and spec_payload:
                truncated = True
                continue
            used += size
            spec_payload.append(entry)

        for candidate in code:
            entry = {
                "path": candidate.metadata.get("path", ""),
                "symbol": candidate.metadata.get("symbol", ""),
                "kind": candidate.metadata.get("code_kind", ""),
                "lines": f"{candidate.metadata.get('start_line')}-{candidate.metadata.get('end_line')}",
                "signature": candidate.metadata.get("signature", ""),
                "source": candidate.metadata.get("source", ""),
                "score": candidate.score,
                "reason": candidate.reasons or ["vector+keyword"],
                "excerpt": self._excerpt(candidate.document),
            }
            size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            if used + size > self.budget_bytes and code_payload:
                truncated = True
                continue
            used += size
            code_payload.append(entry)

        for candidate in tests:
            suite = "regression" if self._is_regression(candidate, suite_by_spec) else "functional"
            entry = {
                "id": candidate.metadata.get("name", candidate.item_id),
                "path": candidate.metadata.get("path", ""),
                "lines": f"{candidate.metadata.get('start_line')}-{candidate.metadata.get('end_line')}",
                "covers": [c.strip() for c in str(candidate.metadata.get("covers", "")).split(",") if c.strip()],
                "source": candidate.metadata.get("source", ""),
                "score": candidate.score,
                "suite": suite,
                "match": candidate.reasons or ["vector+keyword"],
            }
            size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            if used + size > self.budget_bytes:
                truncated = True
                continue
            used += size
            test_payload.append(entry)

        return spec_payload, code_payload, test_payload, truncated

    def _load_progress(self, task_id: str) -> dict[str, Any]:
        if self._state is None:
            return {"available": False, "reason": "state backend not configured", "done": [], "pending": [], "verifications": []}
        record = self._state.load(task_id)
        if record is None:
            return {
                "available": False,
                "reason": "no saved state for task",
                "done": [],
                "pending": [],
                "verifications": [],
            }
        return {
            "available": True,
            "backend": getattr(self._state, "backend_name", "unknown"),
            "revision": record.get("revision"),
            "updated_at": record.get("updated_at"),
            "done": record.get("done", []),
            "pending": record.get("pending", []),
            "verifications": record.get("verifications", []),
        }

    @staticmethod
    def _excerpt(document: str, limit: int = 1200) -> str:
        if len(document) <= limit:
            return document
        return document[:limit] + "\n# ... (已按预算截断，完整内容见 source 行号)"
