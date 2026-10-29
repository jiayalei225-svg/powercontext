"""上下文选择逻辑的单元测试（用内存假存储，不依赖 seekdb）。

假存储复刻了 :class:`sddctx.store.SeekDBStore` 的检索语义：
按余弦相似度排序返回，``score = 1 - distance``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sddctx import chunker
from sddctx.selector import RELATIVE_CUTOFF, ContextBuilder
from sddctx.textutil import cosine, embed

MODULE_ROOT = Path(__file__).resolve().parent.parent


class FakeStore:
    backend_name = "fake"

    def __init__(self) -> None:
        self.data: dict[str, list[dict[str, Any]]] = {"spec": [], "code": [], "test": []}
        self.query_count = 0

    def load_project(self, specs_dir: Path, project_root: Path) -> None:
        for path in chunker.discover(specs_dir, "*.md"):
            _, items = chunker.parse_spec_file(path, specs_dir.parent)
            for item in items:
                self.data["spec"].append(
                    {
                        "document": item.index_text(),
                        "embedding": embed(item.index_text()),
                        "metadata": item.to_metadata(),
                    }
                )
        for path in chunker.discover(project_root / "src", "*.py"):
            for item in chunker.parse_python_symbols(path, project_root, kind="code"):
                self.data["code"].append(
                    {
                        "document": item.index_text(),
                        "embedding": embed(item.index_text()),
                        "metadata": item.to_metadata(),
                    }
                )
        for path in chunker.discover(project_root / "tests", "test_*.py"):
            for item in chunker.parse_python_symbols(path, project_root, kind="test"):
                self.data["test"].append(
                    {
                        "document": item.index_text(),
                        "embedding": embed(item.index_text()),
                        "metadata": item.to_metadata(),
                    }
                )

    def search(self, kind: str, query_embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        self.query_count += 1
        scored = [
            (cosine(query_embedding, item["embedding"]), item) for item in self.data[kind]
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "document": item["document"],
                "metadata": item["metadata"],
                "score": round(max(0.0, score), 6),
            }
            for score, item in scored[:top_k]
        ]

    def list_kind(self, kind: str) -> list[dict[str, Any]]:
        self.query_count += 1
        return [
            {"document": item["document"], "metadata": item["metadata"], "score": 0.0}
            for item in self.data[kind]
        ]

    def get_by_id(self, kind: str, item_id: str) -> dict[str, Any] | None:
        for item in self.data[kind]:
            if item["metadata"].get("item_id") == item_id:
                return {"document": item["document"], "metadata": item["metadata"], "score": 1.0}
        return None

    def count(self, kind: str) -> int:
        return len(self.data[kind])


@pytest.fixture(scope="module")
def store() -> FakeStore:
    fake = FakeStore()
    fake.load_project(
        MODULE_ROOT / "samples" / "specs" / "v1",
        MODULE_ROOT / "sample_project",
    )
    return fake


@pytest.fixture(scope="module")
def task() -> dict[str, Any]:
    return json.loads((MODULE_ROOT / "samples" / "task.json").read_text(encoding="utf-8"))


def test_context_contains_required_sources(store, task):
    context = ContextBuilder(store, None).build(task)
    spec_ids = {item["id"] for item in context["spec_items"]}
    code = {item["source"] for item in context["code_targets"]}
    tests = {
        case["source"]
        for suite in ("functional", "regression")
        for case in context["tests"][suite]
    }
    assert set(task["required_sources"]["specs"]) <= spec_ids
    assert set(task["required_sources"]["code"]) <= code
    assert set(task["required_sources"]["tests"]) <= tests


def test_must_specs_always_included(store, task):
    context = ContextBuilder(store, None).build(task)
    spec_ids = {item["id"] for item in context["spec_items"]}
    assert {"SPEC-ORD-001", "SPEC-ORD-030"} <= spec_ids


def test_irrelevant_specs_are_dropped(store):
    paging_task = json.loads(
        (MODULE_ROOT / "samples" / "task_pagination.json").read_text(encoding="utf-8")
    )
    filter_ctx = ContextBuilder(store, None).build(
        json.loads((MODULE_ROOT / "samples" / "task.json").read_text(encoding="utf-8"))
    )
    paging_ctx = ContextBuilder(store, None).build(paging_task)
    filter_ids = {item["id"] for item in filter_ctx["spec_items"]}
    paging_ids = {item["id"] for item in paging_ctx["spec_items"]}
    assert paging_ids != filter_ids, "不同任务不应返回同一组规格"
    assert "SPEC-ORD-021" not in paging_ids, "分页任务不应召回时间窗口条款"


def test_every_item_carries_traceable_source(store, task):
    context = ContextBuilder(store, None).build(task)
    for item in context["spec_items"]:
        assert "#SPEC-" in item["source"]
    for item in context["code_targets"]:
        assert "::" in item["source"]
    for suite in ("functional", "regression"):
        for case in context["tests"][suite]:
            assert "::" in case["source"]


def test_budget_truncates_and_flags(store, task):
    context = ContextBuilder(store, None, budget_bytes=1_500).build(task)
    assert context["metrics"]["truncated"] is True
    assert context["metrics"]["bytes"] <= 1_500 * 3  # 裁剪按条目粒度，允许最后一条略超


def test_progress_reports_unavailable_without_state(store, task):
    context = ContextBuilder(store, None).build(task)
    assert context["progress"]["available"] is False
    assert context["progress"]["done"] == []


def test_progress_is_filled_from_state(store, task):
    class FakeState:
        backend_name = "powercontext"

        def load(self, task_id: str) -> dict[str, Any]:
            return {
                "done": ["已完成 A"],
                "pending": ["待办 B"],
                "verifications": [{"name": "unit", "passed": True}],
                "seq": 3,
                "updated_at": "2026-04-20T00:00:00+00:00",
            }

    context = ContextBuilder(store, FakeState()).build(task)
    assert context["progress"]["available"] is True
    assert context["progress"]["done"] == ["已完成 A"]
    assert context["progress"]["pending"] == ["待办 B"]
    assert context["progress"]["verifications"][0]["name"] == "unit"


def test_relative_cutoff_keeps_top_scoring_items(store):
    task = json.loads((MODULE_ROOT / "samples" / "task.json").read_text(encoding="utf-8"))
    context = ContextBuilder(store, None).build(task)
    scores = [item["score"] for item in context["spec_items"] if item["priority"] != "must"]
    assert scores, "至少应有一些非 must 条款"
    assert min(scores) >= max(scores) * RELATIVE_CUTOFF - 1e-6
