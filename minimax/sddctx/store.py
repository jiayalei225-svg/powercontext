"""seekdb 存储层。

用 **嵌入式 seekdb**（``pylibseekdb`` + ``pyseekdb``）保存工程资料与向量索引，
不做任何"内存里排一遍"的假检索：上下文选择的候选集全部来自 seekdb 的
向量查询与元数据查询。

三类资料各自一个 collection，便于按类重建：

- ``sddctx_spec``：规格条目
- ``sddctx_code``：源码符号
- ``sddctx_test``：测试用例

注意两个 seekdb 行为，代码里已显式处理：

1. 嵌入式 seekdb 先写入、后建索引；``query`` 之前必须 ``refresh_index()``，
   否则会返回空结果集。
2. ``distance`` 采用 ``cosine`` 距离（``1 - cos``），因此相似度 = ``1 - distance``。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DIM = 384
COLLECTIONS = {
    "spec": "sddctx_spec",
    "code": "sddctx_code",
    "test": "sddctx_test",
}


class SeekDBStore:
    """工程资料索引（seekdb）。"""

    backend_name = "seekdb"

    def __init__(self, path: str | Path, *, query_log: str | Path | None = None) -> None:
        import pyseekdb

        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, exist_ok=True)
        self._pyseekdb = pyseekdb
        self._client = pyseekdb.Client(path=str(self.path))
        self._collections: dict[str, Any] = {}
        self._query_log = Path(query_log) if query_log else None
        if self._query_log:
            self._query_log.parent.mkdir(parents=True, exist_ok=True)
        self.query_count = 0

    # ------------------------------------------------------------------ 初始化

    def collection(self, kind: str, *, recreate: bool = False):
        if kind in self._collections and not recreate:
            return self._collections[kind]
        name = COLLECTIONS[kind]
        if recreate and self._client.has_collection(name):
            self._client.delete_collection(name)
        collection = self._client.get_or_create_collection(
            name=name,
            configuration=self._pyseekdb.HNSWConfiguration(dimension=DIM, distance="cosine"),
            embedding_function=None,
        )
        self._collections[kind] = collection
        return collection

    def reset(self, kinds: tuple[str, ...] = ("spec", "code", "test")) -> None:
        """清空指定种类的资料（重建 collection，避免残留旧版本条目）。"""
        for kind in kinds:
            self.collection(kind, recreate=True)

    # ------------------------------------------------------------------ 写入

    def upsert(self, kind: str, records: list[dict[str, Any]]) -> int:
        """写入一批资料单元。

        ``records`` 每项需包含 ``item_id`` / ``document`` / ``embedding`` / ``metadata``。
        """
        if not records:
            return 0
        collection = self.collection(kind)
        collection.upsert(
            ids=[f"{kind}:{record['item_id']}" for record in records],
            embeddings=[record["embedding"] for record in records],
            documents=[record["document"] for record in records],
            metadatas=[record["metadata"] for record in records],
        )
        return len(records)

    def refresh(self, kinds: tuple[str, ...] = ("spec", "code", "test")) -> None:
        """构建向量索引。写入后不调用会导致查询返回空结果。"""
        for kind in kinds:
            collection = self.collection(kind)
            if collection.count():
                collection.refresh_index()

    # ------------------------------------------------------------------ 查询

    def search(self, kind: str, query_embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        collection = self.collection(kind)
        if collection.count() == 0:
            return []
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: list[dict[str, Any]] = []
        for index, doc_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 1.0
            hits.append(
                {
                    "id": doc_id,
                    "document": documents[index] if index < len(documents) else "",
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "score": round(max(0.0, 1.0 - distance), 6),
                    "distance": round(distance, 6),
                }
            )
        self._log_query(
            {
                "op": "vector_query",
                "collection": COLLECTIONS[kind],
                "top_k": top_k,
                "returned": [hit["id"] for hit in hits],
                "scores": [hit["score"] for hit in hits],
            }
        )
        return hits

    def list_kind(self, kind: str) -> list[dict[str, Any]]:
        collection = self.collection(kind)
        if collection.count() == 0:
            return []
        result = collection.get(include=["documents", "metadatas"])
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        items = [
            {
                "id": ids[index],
                "document": documents[index] if index < len(documents) else "",
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "score": 0.0,
            }
            for index in range(len(ids))
        ]
        self._log_query(
            {
                "op": "metadata_scan",
                "collection": COLLECTIONS[kind],
                "returned_count": len(items),
            }
        )
        return items

    def get_by_id(self, kind: str, item_id: str) -> dict[str, Any] | None:
        collection = self.collection(kind)
        doc_id = f"{kind}:{item_id}"
        result = collection.get(ids=[doc_id], include=["documents", "metadatas"])
        ids = result.get("ids") or []
        if not ids:
            self._log_query(
                {"op": "get_by_id", "collection": COLLECTIONS[kind], "id": doc_id, "hit": False}
            )
            return None
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        self._log_query(
            {"op": "get_by_id", "collection": COLLECTIONS[kind], "id": doc_id, "hit": True}
        )
        return {
            "id": doc_id,
            "document": documents[0] if documents else "",
            "metadata": metadatas[0] if metadatas else {},
            "score": 1.0,
        }

    def count(self, kind: str) -> int:
        return int(self.collection(kind).count())

    def stats(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "library": f"pyseekdb {self._pyseekdb.__version__}",
            "path": str(self.path),
            "collections": {
                COLLECTIONS[kind]: self.count(kind) for kind in COLLECTIONS
            },
            "queries": self.query_count,
        }

    # ------------------------------------------------------------------ 内部

    def _log_query(self, payload: dict[str, Any]) -> None:
        self.query_count += 1
        if not self._query_log:
            return
        with self._query_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def default_query_log() -> Path | None:
    value = os.environ.get("SDDCTX_QUERY_LOG")
    return Path(value) if value else None
