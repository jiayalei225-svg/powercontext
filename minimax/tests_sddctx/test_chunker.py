"""切分器与文本工具的单元测试。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from sddctx import chunker
from sddctx.textutil import build_idf, embed, spec_ids_in, tokenize, weighted_keyword_score

MODULE_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def spec_items():
    path = MODULE_ROOT / "samples" / "specs" / "v1" / "order-list-filter.md"
    _, items = chunker.parse_spec_file(path, path.parent.parent)
    return items


def test_spec_items_have_ids_and_sources(spec_items):
    assert len(spec_items) == 9
    assert [item.id for item in spec_items][0] == "SPEC-ORD-001"
    for item in spec_items:
        assert item.source == f"{item.path}#{item.id}"
        assert item.start_line < item.end_line
        assert item.text.strip()


def test_spec_meta_priority_and_refs(spec_items):
    by_id = {item.id: item for item in spec_items}
    assert by_id["SPEC-ORD-001"].priority == "must"
    assert by_id["SPEC-ORD-030"].priority == "must"
    assert by_id["SPEC-ORD-014"].priority == "normal"
    assert "src/orderhub/api.py::handle_get_orders" in by_id["SPEC-ORD-014"].code_refs


def test_spec_suite_metadata_marks_regression_clause(spec_items):
    by_id = {item.id: item for item in spec_items}
    assert by_id["SPEC-ORD-030"].suite == "regression"
    assert by_id["SPEC-ORD-014"].suite == "functional"


def test_spec_text_does_not_contain_meta_comment(spec_items):
    for item in spec_items:
        assert "meta:" not in item.text


def test_code_symbols_include_path_qualified_id():
    root = MODULE_ROOT / "sample_project"
    symbols = chunker.parse_python_symbols(root / "src" / "orderhub" / "api.py", root, kind="code")
    target = [item for item in symbols if item.symbol == "handle_get_orders"]
    assert target, "handle_get_orders 应被抽取"
    assert target[0].source == "src/orderhub/api.py::handle_get_orders"
    assert target[0].to_metadata()["item_id"] == target[0].source


def test_test_cases_extract_covered_spec_ids():
    root = MODULE_ROOT / "sample_project"
    cases = chunker.parse_python_symbols(root / "tests" / "test_order_filters.py", root, kind="test")
    by_name = {case.name: case for case in cases}
    assert "test_filter_single_status" in by_name
    assert "SPEC-ORD-014" in by_name["test_filter_single_status"].covers


def test_tokenize_handles_mixed_language():
    tokens = tokenize("order_filters 与 订单状态 status")
    assert "order_filters" in tokens
    assert "order" in tokens
    assert "status" in tokens
    assert "订单" in tokens


def test_embed_is_deterministic_and_normalised():
    first = embed("订单列表 status 筛选")
    second = embed("订单列表 status 筛选")
    assert first == second
    norm = math.sqrt(sum(value * value for value in first))
    assert 0.99 < norm < 1.01


def test_embed_differs_for_different_text():
    assert embed("page_size 越界") != embed("created_from 时间窗口")


def test_idf_weighting_favours_rare_tokens():
    corpus = ["订单 列表 接口 分页", "订单 列表 接口 状态", "订单 列表 接口 时间窗口", "page_size 分页 越界"]
    idf, fallback = build_idf(corpus)
    query = tokenize("page_size 分页")
    rare_hit = weighted_keyword_score(query, "page_size 分页 越界", idf, fallback)
    common_hit = weighted_keyword_score(query, "订单 列表 接口", idf, fallback)
    assert rare_hit > common_hit


def test_spec_id_extraction():
    assert spec_ids_in("见 SPEC-ORD-014.2 与 SPEC-ORD-021") == ["SPEC-ORD-014.2", "SPEC-ORD-021"]
