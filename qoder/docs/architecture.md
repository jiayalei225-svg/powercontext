# 架构与实现

## 一句话

PDF → 页级段落 → seekdb（向量 + 全文 + 标量过滤的库内 RRF 融合）→ 页级命中；
用户的检索偏好 → PowerContext（带 revision 的 Memory）→ 每次检索自动转成 seekdb 的 `where`。

## 组件

```
frontend (React 19 + Vite)  ──HTTP──▶  backend (FastAPI)
                                         │
                    ┌────────────────────┴────────────────────┐
                    ▼                                         ▼
            seekdb (pyseekdb 1.4, 嵌入式)              PowerContext 1.4.1
              paper_chunks_* collection                 /v1/memory/remember
              - documents: 段落原文                      /v1/memory/entries/list
              - embeddings: BGE-small-zh 512d            kind=preference / progress
              - metadata: paper/title/year/venue/       带 artifact_id + revision
                field/page/chunk_index/has_code
```

### seekdb 做什么

- **存储**：每个段落一条记录，向量、原文、元数据同库。
- **检索**：`collection.hybrid_search(query=<全文条件>, knn=<向量条件>, rank={"rrf": ...})`。
  - 全文分支：`where_document={"$contains": keyword}`；
  - 向量分支：`query_texts=[query]`；
  - 标量分支：`where`（年份区间、venue `$in`、field、paper_id、has_code）；
  - 三路在 seekdb 内用 RRF 融合，应用层只负责取结果，不做二次拼接。
- **关键词选择**：从 query 的实词中选“当前语料里出现最少”的一个，避免“神经网络”这类高频词
  把全文分支变成噪声。语料文本在内存中缓存，上传/删除时失效。

### PowerContext 做什么

- 偏好写成 `preference` 类型的 Memory，文本带 `paperdesk.prefs.v1|` 前缀和 JSON；
- 每次检索写一条 `progress` Memory，文本带 `paperdesk.search.v1|` 前缀；
- 读取时取 `saved_at` 最新的一条偏好；`artifact_id` 与 `revision` 直接显示在界面上；
- PowerContext 不可用时，`available()` 返回 false，检索继续走 seekdb，只是不带记忆（降级）。

### 数据目录

`data/seekdb/` 是嵌入式数据库目录。seekdb 的原生层无法打开含非 ASCII 字符的路径
（中文用户名、OneDrive 的 `文档` 目录都很常见），因此 `config.py` 会：

1. 优先使用 `PAPERDESK_DATA_DIR`（或仓库下的 `data/`）；
2. 如果绝对路径含非 ASCII，自动回退到 `%LOCALAPPDATA%\PaperDesk\data` 并打印提示；
3. 上传文件与 seekdb 数据都落在这个目录，`.gitignore` 已排除。

### 性能

一次检索的耗时分布（本机，12 段样例，Windows 11 / Python 3.13）：

| 版本 | 中位耗时 | 原因 |
| --- | --- | --- |
| 优化前 | ~6500 ms | 每次检索新建 3 个 HTTP 连接访问 PowerContext（本机建连 ~1.5 s），另加 3 次 `$contains` 稀有度探测 |
| 优化后 | **~115 ms** | 复用 `httpx.Client` 连接池；偏好 10 s TTL 缓存；语料文本缓存；关键词探测降为内存扫描 |

首次请求仍需 ~0.8 s（加载模型/建连），已通过 FastAPI 启动预热把模型加载放在启动阶段。

## 关键文件

| 文件 | 职责 |
| --- | --- |
| `backend/app/ingest.py` | PDF 解析、按页切块、论文 ID（文件内容 SHA-256） |
| `backend/app/store.py` | seekdb collection、写入/删除、混合检索、语料缓存 |
| `backend/app/memory.py` | PowerContext 客户端、偏好/检索日志、健康缓存与连接池 |
| `backend/app/search.py` | 偏好合并、关键词选择、检索编排、降级 |
| `backend/app/main.py` | FastAPI 路由、启动预热、静态站点托管 |
| `frontend/src/App.tsx` | 三栏界面、检索、记忆面板 |
| `scripts/verify.py` | 14 项端到端断言 |
| `scripts/seed.py` | 导入 4 篇样例 |
| `scripts/make_samples.py` | 生成样例 PDF（自撰阅读笔记） |
