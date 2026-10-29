# 技术使用记录

本文件记录三项技术的实际使用情况。原始证据全部在仓库内，可按路径核对。

## 一、MiniMax 使用记录

### 接入方式与版本

1. 接口：`POST https://api.minimax.chat/v1/text/chatcompletion_v2`，Bearer 鉴权
2. SDK：未使用官方 SDK，用 `httpx` 直接调用（`agent/minimax_client.py`），版本约束见 `requirements.txt`
3. 模型：`MiniMax-M1`
4. 关键实现细节：
   - MiniMax 出错时仍返回 HTTP 200，真实错误码在 `base_resp.status_code`，客户端据此判断；
   - `1039 rate limit exceeded(TPM)` 属可重试，退避 20/45/90/120/180 秒；
   - 推理模型返回 `reasoning_content`，本作品**不采集**其内容，只记录是否存在与字符数。

### 模型选择过程（可复现）

在 `api.minimax.chat` 上逐个尝试模型名，响应如下：

1. `MiniMax-M2.7`、`MiniMax-M2.5`、`MiniMax-M2.1`、`MiniMax-M2`、`M2-her`、`abab6.5s-chat` → `code 2069`，模型不可用
2. `MiniMax-Text-01` → `code 0`，可用
3. `MiniMax-M1` → `code 0`，可用（最终选用，因其为推理模型、代码能力更强）

海外端点 `api.minimax.io` 与 `api.minimaxi.chat` 对该 Key 返回 `code 2049 invalid api key`，
说明该 Key 属国内区，故固定使用 `api.minimax.chat`。

### TPM 限额实测

用递增输入 + 固定输出预留探测（每次间隔 65 秒）：

1. 625 字符 + `max_tokens=500` → 成功，用量 753 tokens
2. 2425 字符 + `max_tokens=2000` → 成功，prompt 1747 tokens
3. 4825 字符 + `max_tokens=4000` → 成功，prompt 3107 tokens
4. 9625 字符 + `max_tokens=8000` → `code 1039 rate limit exceeded(TPM)`

结论：限额约 10K TPM。据此在 `agent/run_task.py` 里设 `TPM_BUDGET=9000`，
并按下式动态决定输出上限：`max_tokens = max(1500, min(配置上限, 9000 - prompt_tokens))`。

### 三次真实调用

原始请求与响应分别在 `artifacts/logs/minimax/<时间戳>_attempt<编号>_request.json`
与 `_response.json`，摘要追加在 `artifacts/logs/minimax-devlog.jsonl`。

第一次：`attempt 1-service`，聚焦 `src/orderhub/service.py`

1. request_id：`0731e7049a8b16b5687106854ee44c44`
2. prompt 7912 字符（估算 2812 tokens），`max_tokens=6188`
3. 用量：prompt 2788 + completion 3534 = 6322 tokens；耗时 28.9 秒
4. 结果：生成 `service.py`，新增 `status`/`created_from`/`created_to` 参数、
   `_normalize_status`、`_parse_datetime`、UTC 归一化与闭区间比较、筛选后 `total`
5. 模型自述覆盖：`SPEC-ORD-014`、`SPEC-ORD-014.1`、`SPEC-ORD-014.2`、`SPEC-ORD-021`、
   `SPEC-ORD-021.1`、`SPEC-ORD-024`、`SPEC-ORD-030`

第二次：`attempt 2-api`，聚焦 `src/orderhub/api.py`

1. request_id：`0731e7384e18f3c80cc66f627fb7cd23`
2. prompt 9877 字符（估算 3418 tokens），`max_tokens=5582`
3. 用量：prompt 3344 + completion 2020 = 5364 tokens；耗时 15.4 秒
4. 传给模型的上一步结论（`--done` 参数）写明 `service.py` 新签名与"不要重复实现校验"，
   模型据此只做查询串解析与透传
5. 结果：`params.get("status", [])` 取多值、`_first` 取时间参数，调用 `service.list_orders(...)`

第三次：`attempt 3-fix`，聚焦 `src/orderhub/service.py`，携带测试失败反馈

1. request_id：`0731e788d5b666b9823352d141f0cde0`
2. prompt 12153 字符（估算 4175 tokens），`max_tokens=4825`
3. 用量：prompt 4046 + completion 2711 = 6757 tokens；耗时 18.6 秒
4. 触发原因：`tests/test_order_filters.py::test_invalid_date_format_rejected` 失败——
   `created_from=2026-13-45` 时 `_parse_datetime` 抛出 `ValueError` 而非规格要求的
   `ApiError("invalid_range")`。反馈原文见 `_feedback.txt` 同内容，已写入 request 的 `feedback` 字段
5. 结果：把无法解析的时间输入统一转为 `ApiError("invalid_range", ...)`，不向上泄漏 `ValueError`

### 开发记录与代码差异的对应

`verify_all.py` 的 B 项做三件事：

1. 读 `minimax-devlog.jsonl`，取出 `files_written` 非空的记录；
2. 与 `git diff --name-only HEAD~1 HEAD` 的文件清单比对，要求有交集；
3. 重算 response 内容的 sha256 与日志里的 `response_sha256` 比对，确保响应文件未被替换。

## 二、seekdb 使用记录

### 接入方式与版本

1. 包：`pyseekdb==1.4.0.post1` + `pylibseekdb==1.4.0.post2`（嵌入式引擎）
2. 模式：嵌入式，数据落在 `minimax/.data/seekdb/`，无需单独启动数据库进程
3. 距离度量：`cosine`，相似度取 `1 - distance`

### 三个 collection

1. `sddctx_spec`：规格条款，元数据含 `item_id`、`doc_id`、`spec_version`、`priority`、`suite`、`code_refs`、`source`
2. `sddctx_code`：代码符号，元数据含 `symbol`、`code_kind`、`path`、`start_line`、`end_line`、`signature`、`source`
3. `sddctx_test`：测试用例，元数据含 `name`、`path`、`covers`（覆盖的规格编号）、`source`

### 一个必须处理的坑

嵌入式 seekdb 写入后不立即建索引，直接 `query` 会返回空结果集。必须先 `refresh_index()`。
`SeekDBStore.refresh()` 在每次 `upsert` 后被调用；这一行为在早期调试中确认过
（写入 3 条后 `query` 返回空，`refresh_index()` 后正常返回）。

### 查询审计

每次查询都追加到 `artifacts/logs/seekdb-queries.jsonl`，字段为 `op`、`collection`、
`top_k`/`returned`/`scores` 或 `id`/`hit`。`op` 取值：

1. `vector_query`：向量检索
2. `metadata_scan`：按类全量扫描（用于 must 条款保底与测试覆盖关系匹配）
3. `get_by_id`：按 `路径::符号` 精确取代码符号

`verify_all.py` 的 D 项读取该日志，比对两件事：三个 collection 计数是否都大于 0；
`vector_query` 返回的 `spec:*` 编号与上下文实际使用的 spec 编号是否有交集。

## 三、PowerContext 使用记录

### 接入方式与版本

1. 包：`powercontext[cli,server]==1.4.1`
2. Server：`scripts/run_powercontext.py`，用 `ServerSettings` + `create_server_app` + `uvicorn` 直接组装，
   存储为本地 SQLite（`sqlite+aiosqlite:///<data-dir>/powercontext.sqlite3`）
3. 客户端：`PowerContextClient`（异步），封装在 `sddctx/state.py`
4. 选型理由：官方 `config init` 是交互式向导，不适合"一条命令复现"；直接用 `ServerSettings`
   可把工作区、端口、数据库路径全部显式指定

### 写入方式

1. `create_scope`：首次运行时创建工程 Scope，`idempotency_key="sddctx-scope-v1"`；
   Scope ID 缓存在 `.data/state/scope.json`，避免重复创建
2. `remember_memory`：任务状态写成 `kind="state"` 的 Atomic Memory，正文前缀 `SDDCTX-TASK-STATE v1 `，
   后接带 `seq` 的 JSON 快照
3. 每次保存 `seq = 上次 seq + 1`，并记录 `previous_seq`，形成可追溯的版本链

### 读取方式

`list_memory_entries`（`limit=100`，按 `next_cursor` 翻页，最多 10 页）→ 过滤出前缀匹配且
`task_id` 相同的记录 → 取 `seq` 最大者。上下文输出的 `progress` 段直接来自这里。

### 状态复用实测

`verify_all.py` 的 E 项用独立 `task_id=VERIFY-STATE-001` 走三步，全部在不同进程里：

1. 空状态下 `state save` 写入 `done`/`pending`/`verifications`，记录返回的 `seq` 与 Scope
2. 另起进程 `state show` 读回，比对 `done` 完全一致
3. 再起进程 `context` 构造上下文，要求 `progress.available=true`、
   `progress.backend="powercontext"`、`progress.done` 与写入内容一致、`verifications` 数量 ≥ 1

样例任务 `ORD-FILTER-001` 的真实状态（`python -m sddctx.cli state show --task-id ORD-FILTER-001` 可复现）：
`seq=4`，含 4 条 `done`、2 条 `verifications`（`target-tests` 退出码 0、`regression-tests` 退出码 0），
`artifact_id=art_39202c4726614409a60056ed369916af`。

### 一次踩坑记录

`ListMemoryEntriesRequest.limit` 上限是 100，早期传 200 被 pydantic 拒绝；
改为按 `limit=100` + 游标翻页后正常。这一修正保留在 `sddctx/state.py` 的实现里。
