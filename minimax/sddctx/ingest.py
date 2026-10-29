"""资料导入：切分 → 向量化 → 写入 seekdb。

导入是**幂等 + 全量替换**：重导入规格时会先重建 ``sddctx_spec`` collection，
所以规格改版后不会残留旧条款，上下文输出必然使用新内容。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import chunker
from .store import SeekDBStore
from .textutil import embed


def _record(item) -> dict[str, Any]:
    document = item.index_text()
    metadata = item.to_metadata()
    return {
        "item_id": metadata["item_id"],
        "document": document,
        "embedding": embed(document),
        "metadata": metadata,
    }


def ingest_specs(store: SeekDBStore, specs_dir: str | Path, project_root: str | Path | None = None) -> dict[str, Any]:
    """导入目录下所有 Markdown 规格。"""
    specs_dir = Path(specs_dir)
    # 来源路径相对于规格目录的上一级，输出形如 specs/v1/order-list-filter.md#SPEC-ORD-014
    root = specs_dir.parent if specs_dir.parent.exists() else specs_dir
    if not specs_dir.exists():
        raise FileNotFoundError(f"规格目录不存在：{specs_dir}")

    documents: list[dict[str, Any]] = []
    items = []
    for path in chunker.discover(specs_dir, "*.md"):
        doc_meta, doc_items = chunker.parse_spec_file(path, root)
        doc_meta["abs_path"] = str(path)
        documents.append(doc_meta)
        items.extend(doc_items)

    store.reset(("spec",))
    written = store.upsert("spec", [_record(item) for item in items])
    store.refresh(("spec",))
    return {
        "kind": "spec",
        "documents": documents,
        "items": len(items),
        "written": written,
        "item_ids": [item.id for item in items],
    }


def ingest_code(store: SeekDBStore, project_root: str | Path) -> dict[str, Any]:
    """导入业务工程源码符号。"""
    project_root = Path(project_root)
    src_root = project_root / "src"
    root = src_root if src_root.exists() else project_root
    items = []
    for path in chunker.discover(root, "*.py"):
        items.extend(chunker.parse_python_symbols(path, project_root, kind="code"))
    store.reset(("code",))
    written = store.upsert("code", [_record(item) for item in items])
    store.refresh(("code",))
    return {
        "kind": "code",
        "items": len(items),
        "written": written,
        "symbols": [item.symbol for item in items],
    }


def ingest_tests(store: SeekDBStore, project_root: str | Path) -> dict[str, Any]:
    """导入测试用例，并从 docstring 里建立"测试 → 规格"的覆盖关系。"""
    project_root = Path(project_root)
    items = []
    for path in chunker.discover(project_root / "tests", "test_*.py"):
        items.extend(chunker.parse_python_symbols(path, project_root, kind="test"))
    store.reset(("test",))
    written = store.upsert("test", [_record(item) for item in items])
    store.refresh(("test",))
    return {
        "kind": "test",
        "items": len(items),
        "written": written,
        "covers": {item.name: item.covers for item in items},
    }


def ingest_all(
    store: SeekDBStore,
    *,
    project_root: str | Path,
    specs_dir: str | Path,
) -> dict[str, Any]:
    return {
        "specs": ingest_specs(store, specs_dir, project_root),
        "code": ingest_code(store, project_root),
        "tests": ingest_tests(store, project_root),
    }
