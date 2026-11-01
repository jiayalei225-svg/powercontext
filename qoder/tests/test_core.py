from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import index, pdf, recall, serialize
from app.settings import settings

ROOT = Path(__file__).resolve().parents[1]


def test_split_pages_keeps_sentences_and_overlap():
    pages = [
        "混合检索把向量召回与词法召回放在同一个引擎里。" * 30,
        "标量过滤条件需要同时下推到两个召回分支。" * 30,
    ]
    chunks = pdf.split_pages(pages)
    assert len(chunks) >= 3
    assert all(len(chunk.text) <= pdf.TARGET_CHARS + pdf.OVERLAP_CHARS + 80 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page in {1, 2} for chunk in chunks)
    assert chunks[-1].page == 2


def test_read_meta_prefers_header_fields():
    pages = [
        "标题：面向检索的测试方法\n会议：SIGIR\n年份：2024\n方向：信息检索\n代码：https://github.com/demo/repo\n"
        "摘要：这是一段用于测试的文本。",
        "",
    ]
    meta = pdf.read_meta(pages, "fallback.pdf")
    assert meta.title == "面向检索的测试方法"
    assert meta.year == 2024
    assert meta.venue == "SIGIR"
    assert meta.field == "信息检索"
    assert meta.has_code is True
    assert meta.code_url == "https://github.com/demo/repo"


def test_read_meta_falls_back_to_filename():
    meta = pdf.read_meta(["", ""], "my-paper_v2.pdf")
    assert meta.title == "my paper v2"
    assert meta.year is None
    assert meta.venue == "未标注"
    assert meta.has_code is False


def test_build_where_combines_scalar_filters():
    where = index.build_where(
        {"year_from": 2023, "year_to": 2025, "venues": ["ACL"], "field": "RAG", "has_code": True}
    )
    assert where == {
        "year": {"$gte": 2023, "$lte": 2025},
        "venue": {"$in": ["ACL"]},
        "field": "RAG",
        "has_code": 1,
    }
    assert index.build_where({}) is None


def test_plan_merges_memory_defaults():
    prefs = {"year_from": 2024, "venues": ["ACL"], "only_with_code": True, "field": "检索增强生成"}
    filters, applied, notes = recall.plan(prefs, {"use_memory": True})
    assert filters["year_from"] == 2024
    assert filters["venues"] == ["ACL"]
    assert filters["has_code"] is True
    assert filters["field"] == "检索增强生成"
    assert set(applied) == {"year_from", "venues", "only_with_code", "field"}
    assert len(notes) == 4


def test_plan_request_wins_over_memory():
    prefs = {"year_from": 2024, "venues": ["ACL"], "only_with_code": True, "field": "检索增强生成"}
    filters, applied, notes = recall.plan(prefs, {"year_from": 2020, "has_code": False}, use_memory=True)
    assert filters["year_from"] == 2020
    assert filters["has_code"] is False
    assert "year_from" not in applied
    assert applied["venues"] == ["ACL"]
    assert len(notes) == 2


def test_diversify_caps_chunks_per_paper():
    hits = [
        {"metadata": {"paper_id": "a"}},
        {"metadata": {"paper_id": "a"}},
        {"metadata": {"paper_id": "a"}},
        {"metadata": {"paper_id": "b"}},
    ]
    picked = recall._diversify(hits, limit=3)
    assert [hit["metadata"]["paper_id"] for hit in picked] == ["a", "a", "b"]
    assert len(recall._diversify(hits + [{"metadata": {"paper_id": "c"}}], limit=5)) == 4


def test_snippet_centers_on_query_term():
    text = "前文" * 100 + "seekdb 的混合检索接口" + "后文" * 100
    cut = recall.snippet(text, ["混合检索"], width=120)
    assert "混合检索" in cut
    assert cut.startswith("…")
    assert cut.endswith("…")
    assert len(cut) <= 122


def test_exports_include_hit_and_filters():
    payload = {
        "query": "混合检索",
        "strategy": "hybrid",
        "literal": "混合检索",
        "total": 1,
        "filters": {"year_from": 2023, "venues": ["SIGIR"], "has_code": True},
        "notes": ["记忆偏好：只看 2023 年以后的文献"],
        "results": [
            {
                "title": "测试论文",
                "year": 2024,
                "venue": "SIGIR",
                "page": 3,
                "has_code": True,
                "code_url": "https://github.com/demo/repo",
                "paper_id": "pd2_demo",
                "snippet": "片段内容",
                "text": "片段内容",
            }
        ],
    }
    markdown = serialize.markdown(payload)
    assert "# PaperDesk 检索报告" in markdown
    assert "测试论文" in markdown
    assert "https://github.com/demo/repo" in markdown
    csv_text = serialize.csv_text(payload)
    assert csv_text.startswith("\ufeff")
    assert "测试论文" in csv_text
    assert "混合检索" in csv_text


def test_sample_pdf_is_readable():
    sample = ROOT / "samples" / "01-adaptive-hybrid-retrieval.pdf"
    if not sample.is_file():
        pytest.skip("sample corpus not generated")
    pages = pdf.read_pages(sample)
    assert len(pages) >= 2
    meta = pdf.read_meta(pages, sample.name)
    assert "混合检索" in meta.title
    assert meta.year == 2024
    meta_payload = json.loads(json.dumps(meta.__dict__, ensure_ascii=False, default=str))
    assert meta_payload["has_code"] is True


def test_seekdb_roundtrip(tmp_path):
    settings.data_dir = tmp_path / "data"
    settings.prepare()
    index.reset()
    meta = pdf.PaperMeta(title="临时测试论文", year=2025, venue="TEST", field="测试", has_code=True)
    chunks = [
        pdf.Chunk(index=0, page=1, text="这段文字讨论向量数据库中的混合检索与标量过滤。"),
        pdf.Chunk(index=1, page=2, text="PowerContext 用来保存用户偏好，并在下一次检索时重新应用。"),
    ]
    paper_id = "pd2_testpaper"
    index.add(paper_id, meta, chunks)

    stats = index.stats()
    assert stats["papers"] == 1
    assert stats["chunks"] == 2

    hits = index.hybrid("向量数据库的混合检索", "混合检索", None, 5)
    assert hits and hits[0]["metadata"]["paper_id"] == paper_id

    filtered = index.hybrid("混合检索", "混合检索", {"has_code": 1, "year": {"$gte": 2025}}, 5)
    assert filtered
    empty = index.nearest("混合检索", {"year": {"$lte": 2020}}, 5)
    assert empty == []

    detail = index.paper(paper_id)
    assert detail and len(detail["chunk_details"]) == 2
    assert index.remove(paper_id) is True
    assert index.papers() == []
    index.reset()
