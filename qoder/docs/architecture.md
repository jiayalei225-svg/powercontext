# 架构说明

## 总览

PaperDesk 2.0 由三个角色组成：

```text
React 前端  ──HTTP──▶  FastAPI 后端  ──▶  seekdb（论文片段的唯一存储与检索引擎）
                            │
                            └────────▶  PowerContext（偏好与检索轨迹的唯一持久层）
```

- 前端只负责表单、检索计划展示与原文片段阅读，不直接访问数据库。
- 后端不使用内存倒排或额外的向量数据库；混合检索完全由 seekdb 完成。
- 用户偏好与检索轨迹不写本地 JSON，而是以带标记的条目写入 PowerContext，并通过 artifact revision 追溯。

## 模块划分

| 模块 | 职责 |
| --- | --- |
| `backend/app/settings.py` | 读取 `.env`，选择数据目录，非 ASCII 路径自动回退 |
| `backend/app/embedding.py` | 本地 ONNX BGE 或 OpenAI 兼容嵌入；集合名随模型后缀变化 |
| `backend/app/pdf.py` | PyMuPDF 文本抽取、头部元数据识别、句读感知分块 |
| `backend/app/index.py` | seekdb 集合、批量写入、删除、过滤条件、`hybrid_search` |
| `backend/app/memory.py` | PowerContext 客户端、偏好/轨迹标记、快照 |
| `backend/app/recall.py` | 分词、字面锚点选择、记忆合并、片段摘要、结果多样化 |
| `backend/app/serialize.py` | Markdown / CSV 导出 |
| `backend/app/server.py` | FastAPI 路由、上传校验、静态前端托管、启动预热 |

## 入库流程

```text
PDF ──PyMuPDF──▶ 每页文本 ──┬──▶ 头部字段（标题/会议/年份/方向/代码）
                            └──▶ 句读分块（目标 380 字，重叠 70 字）
                                      │
                                      ▼
                           metadata + document 批量 upsert
                                      │
                                      ▼
                           seekdb collection: paper_chunks_v2_bge_zh
```

要点：

1. **ID 可复现**：`paper_id = "pd2_" + sha1(pdf_bytes)[:14]`，重复上传直接返回已有论文。
2. **元数据可缺失**：优先解析 PDF 头部的“标题 / 会议 / 年份 / 方向 / 代码”，缺失时回退到文件名与“未标注”。
3. **分块可回溯**：每个 chunk 保存 `paper_id`、页码、序号、标题、年份、会议、方向、`has_code`、代码链接。
4. **批量写入**：每 48 个 chunk 一次 `upsert`，写完调用 `refresh_index()` 并失效语料缓存。
5. **集合与模型绑定**：集合名为 `paper_chunks_v2_<embedding_suffix>`，避免换模型后维度不匹配。

## 检索流程

```text
用户问题
  │
  ├─ jieba 词性筛选 ──▶ 查询词项
  ├─ 语料稀有度探测 ──▶ 字面锚点（用于全文召回的 $contains）
  └─ PowerContext 偏好 ──▶ 合并为 filters（显式条件优先）
                │
                ▼
seekdb.hybrid_search(
  query={n_results, where_document: {$contains: 锚点}, where},
  knn={query_texts: [问题], n_results, where},
  rank={rrf: {rank_window_size: 60, rank_constant: 60}},
  n_results=limit
)
                │
                ▼
       按论文去重（每篇最多 2 段）──▶ 片段摘要 / 高亮 ──▶ 返回检索计划
                │
                └──▶ PowerContext 写入一条 progress 轨迹
```

### 为什么用 seekdb 的 `hybrid_search`

本项目的核心不是“把两路结果在应用层拼起来”，而是把三条约束同时下推到一次查询：

- **语义召回**：dense KNN 处理同义表达；
- **字面召回**：full-text `$contains` 保证专有名词、编号、缩写不被向量稀释；
- **结构过滤**：年份、会议、方向、开源标记同时作用于两路召回；
- **融合排序**：seekdb 内置 RRF，不引入第二套检索服务或手写分数归一化。

这使检索路径保持为一个引擎、一个集合、一次调用，便于在本地复现。后端仅在混合检索为空时退化为纯向量召回。

### 过滤字段

| 字段 | seekdb 条件 | 说明 |
| --- | --- | --- |
| `year_from` | `year >= n` | 年份下界 |
| `year_to` | `year <= n` | 年份上界 |
| `venues` | `venue in [...]` | 会议/期刊 |
| `field` | `field == "..."` | 研究方向 |
| `paper_id` | `paper_id == "..."` | 单篇定位 |
| `has_code` | `has_code == 1` | 开源标记以整数存储 |

### 结果多样化

混合检索按相关度返回后会按 `paper_id` 计数，每篇最多保留 2 个片段，再截断到请求的 `limit`。这样既保留“同一篇论文的不同段落”这一有用信息，又避免一篇论文占据整个结果列表。

## PowerContext 记忆协议

### 条目格式

PowerContext 的条目是文本。PaperDesk 用两个命名空间标记区分业务数据：

```text
paperdesk2/prefs/v1|{"year_from":2024,"venues":["ACL"],"only_with_code":true,...}
paperdesk2/trace/v1|{"query":"...","filters":{...},"hits":6,"at":1760000000}
```

- `kind=preference`：保存用户偏好，文本带 `saved_at`，读取时选最新版本。
- `kind=progress`：每次检索一条，用于“最近检索轨迹”和任务复现。
- 所有条目都来自 `POST /v1/memory/remember`；读取使用 `POST /v1/memory/entries/list`（上限 100 条）。
- 保存响应中的 `artifact.artifact_id` 与 `artifact.revision` 会在界面展示，便于确认记忆确实落盘。

### 合并规则

`recall.plan()` 按字段逐个判断：

1. 用户本次显式填写了该字段 → 使用用户值；
2. 未填写且记忆里有该字段 → 使用记忆值，并记录一条“记忆偏好”说明；
3. 两者都没有 → 不加该过滤。

因此记忆永远只是默认值，不会覆盖本次显式条件。界面上的“应用记忆偏好”开关可以整体关闭记忆参与。

### 降级行为

- PowerContext 健康检查失败（TTL 4 秒）时，检索仍然工作，`memory_connected=false`，计划面板提示“记忆服务不可用”。
- 记忆写入失败不会阻断检索结果返回，但会在响应中带 `memory_error`。
- 记忆服务不可用时，前端仍可上传、检索、删除和导出。

## 数据目录

```text
data/
├── uploads/   # 原始 PDF（以 paper_id 命名）
└── seekdb/    # seekdb 数据库文件
```

seekdb 原生层不能打开含非 ASCII 字符的路径。`settings.py` 在启动时检查 `PAPERDESK_DATA_DIR` 或项目内 `data/`，若包含非 ASCII 字符则自动回退到 `%LOCALAPPDATA%\PaperDesk\data-v2`，并在控制台说明。数据和索引都只在本机。

## 前端

- React 19 + TypeScript + Vite，构建产物由 FastAPI 直接托管。
- 三个页签：检索、文献库、记忆；URL hash 可刷新、可前进后退。
- 检索结果展示“检索计划”（词项、字面锚点、过滤、记忆来源、耗时）和原文片段高亮。
- 论文详情以抽屉呈现全部片段，可打开原始 PDF 与代码链接。
- 文献库支持拖拽上传、重复检测、删除；记忆页支持偏好编辑、清除、查看轨迹与 artifact。

## 边界与取舍

- 未引入用户系统：单机单用户，PowerContext 默认 scope 即当前用户。
- 未引入 rerank 模型：RRF 已能体现混合检索，rerank 会增加本地依赖与延迟。
- 分词采用 jieba 词性筛选；字面锚点取“语料中出现次数最少”的词项，以减少全文召回的误命中。
- PDF 只处理文本层；扫描件需先 OCR，不在本项目范围内。
