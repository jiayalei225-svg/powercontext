# API 说明

默认基址：`http://127.0.0.1:8080`（可用 `PAPERDESK_PORT` 修改）。交互式文档在 `/api/docs`。

## 健康检查

```http
GET /api/health
```

```json
{
  "status": "ok",
  "version": "2.0.0",
  "data_dir": "<本地数据目录>",
  "index": {
    "collection": "paper_chunks_v2_bge_zh",
    "papers": 5,
    "chunks": 26,
    "embedding": "bge-small-zh-v1.5"
  },
  "memory": {
    "connected": true,
    "url": "http://127.0.0.1:18000",
    "scope_id": "<PowerContext scope>"
  }
}
```

## 文献

```http
GET /api/papers
```

返回 `{ "total": 5, "papers": [...] }`，每篇包含 `paper_id`、标题、年份、会议、方向、`has_code`、`chunks`、`pages`。

```http
POST /api/papers
Content-Type: multipart/form-data
```

字段名为 `file`，仅接受 PDF：

```bash
curl -X POST http://127.0.0.1:8080/api/papers \
  -F "file=@samples/01-adaptive-hybrid-retrieval.pdf"
```

```json
{
  "duplicate": false,
  "added": 6,
  "paper": {
    "paper_id": "pd2_e3c208b1505130",
    "title": "面向向量数据库的混合检索自适应融合方法",
    "year": 2024,
    "venue": "计算机学报",
    "chunks": 6
  }
}
```

```http
GET /api/papers/{paper_id}
DELETE /api/papers/{paper_id}
GET /api/papers/{paper_id}/file
```

详情包含 `chunk_details`（按页码、序号排序）；`file` 返回原始 PDF；删除会同时移除 seekdb 中的向量与本地文件。

## 检索

```http
POST /api/search
Content-Type: application/json
```

```json
{
  "query": "向量数据库里怎么做混合检索",
  "limit": 12,
  "year_from": null,
  "year_to": null,
  "venues": null,
  "field": null,
  "has_code": null,
  "paper_id": null,
  "use_memory": true
}
```

响应（截断）：

```json
{
  "query": "向量数据库里怎么做混合检索",
  "terms": ["检索", "向量", "数据库", "混合"],
  "literal": "数据库",
  "strategy": "hybrid",
  "total": 10,
  "limit": 12,
  "filters": {
    "year_from": null,
    "year_to": null,
    "venues": [],
    "field": null,
    "paper_id": null,
    "has_code": null
  },
  "applied": {},
  "notes": [],
  "memory_connected": true,
  "memory_error": null,
  "elapsed_ms": 124,
  "results": [
    {
      "chunk_id": "pd2_e3c208b1505130:0",
      "paper_id": "pd2_e3c208b1505130",
      "title": "面向向量数据库的混合检索自适应融合方法",
      "year": 2024,
      "venue": "计算机学报",
      "field": "向量数据库",
      "page": 1,
      "has_code": true,
      "code_url": "https://github.com/jiayalei225-svg/powercontext",
      "snippet": "…",
      "text": "…",
      "score": 0.016
    }
  ]
}
```

当记忆中有偏好且本次未显式填写时：

```json
{
  "applied": {
    "year_from": 2024,
    "venues": ["ACL", "CVPR"],
    "only_with_code": true
  },
  "notes": [
    "记忆偏好：只看 2024 年以后的文献",
    "记忆偏好：限定在 ACL、CVPR",
    "记忆偏好：只看带开源代码的论文"
  ]
}
```

显式条件永远优先。例如请求里给出 `"year_from": 2023, "venues": ["SIGIR"]`，则 `applied` 不会包含这两个字段。

## 导出

```http
POST /api/search/export
POST /api/search/export.csv
```

请求体与 `/api/search` 相同。返回 `text/markdown` 或 `text/csv` 附件；CSV 带 UTF-8 BOM，便于 Excel 直接打开中文。

```bash
curl -X POST http://127.0.0.1:8080/api/search/export \
  -H "Content-Type: application/json" \
  -d '{"query":"混合检索","limit":5}' \
  -o report.md
```

## 记忆

```http
GET /api/preferences
PUT /api/preferences
```

保存：

```json
{
  "year_from": 2024,
  "venues": ["ACL"],
  "only_with_code": true,
  "field": "检索增强生成"
}
```

响应包含 `artifact` 与 `revision`：

```json
{
  "connected": true,
  "artifact": "art_...",
  "revision": 1,
  "preferences": {
    "year_from": 2024,
    "venues": ["ACL"],
    "only_with_code": true,
    "field": "检索增强生成"
  }
}
```

清除偏好：提交所有字段为空/默认值即可，读取将返回 `{}`。

```http
GET /api/history
GET /api/memory
```

- `history`：`connected`、`scope_id`、最近的 `searches`。
- `memory`：`connected`、`scope_id`、`preferences`、`searches`、`entries`（含 artifact / revision / kind / state）。

## 错误

| 状态码 | 场景 |
| --- | --- |
| 400 | 文件不是 PDF、PDF 无法解析、参数非法 |
| 404 | 论文不存在 |
| 413 | 文件超过 40 MB |
| 503 | PowerContext 未连接（仅偏好写入） |

未启动 PowerContext 时，检索仍返回结果，`memory_connected` 为 `false`。
