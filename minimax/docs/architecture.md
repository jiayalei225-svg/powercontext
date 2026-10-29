# 一页技术说明

## 这个模块解决什么

AI 开发助手改代码时缺三样东西：该遵守哪些规格、该改哪些代码、怎么验证。资料散落、规格会变、任务会中断，
于是出现漏约束、用旧规格、重复劳动。`sddctx` 把这三样从"对话里"搬到"可检索、可追溯、可复用"的工程资产上。

## 模块结构

```
任务 JSON
   │
   ├─ ingest ──→ 切分器 ──→ seekdb（三类 collection）
   │              规格→条款；代码→符号；测试→用例+覆盖关系
   │
   └─ context ─→ 选择器 ──→ 开发上下文 JSON
                   │            ├─ spec_items（条款 + 来源 + 行号）
                   │            ├─ code_targets（符号 + 签名 + 摘录）
                   │            ├─ tests.functional / tests.regression
                   │            └─ progress（来自 PowerContext）
                   └─ state ──→ PowerContext（任务进展快照，seq 递增）
```

代码分层：

1. `sddctx/chunker.py`：三类资料切成可检索单元。规格按 `### SPEC-XXX-000` 切条款，元数据写在
   `<!-- meta: priority=...; code_refs=...; suite=... -->` 里；代码用 `ast` 抽类/函数并保留行号与签名；
   测试从 docstring 自动抽取它覆盖的规格条款编号，形成"测试↔规格"双向索引。
2. `sddctx/store.py`：嵌入式 seekdb（`pyseekdb` + `pylibseekdb`）。三类资料各自一个 collection，
   导入是"重建 collection + 全量写入 + `refresh_index()`"，所以规格改版后不会残留旧条款。
3. `sddctx/selector.py`：候选来源于 seekdb 的向量查询与元数据查询，再融合三路信号排序。
4. `sddctx/state.py`：把任务进展写成 PowerContext 的 Atomic Memory（`kind=state`，正文是带 `seq` 的 JSON 快照），
   读取时取该任务 `seq` 最大者。
5. `agent/`：MiniMax 客户端与开发任务编排；`scripts/` 与 `sddctx/cli.py` 是对外入口。

## 上下文怎么选出来

排序分三路，权重写在 `selector.WEIGHTS`：

1. **向量分（0.45）**：seekdb 余弦相似度（`score = 1 - cosine distance`）。
2. **关键词分（0.35）**：IDF 加权覆盖率。`created_from`、`page_size` 这类稀有标识符权重高，
   `订单`、`列表` 这类高频词权重接近 0——这是不同任务能选出不同条款的关键。
3. **结构分（0.20）**：规格 `code_refs` 精确展开到代码符号、测试 `covers` 精确挂到规格、任务声明的
   `touched_paths` 加权。结构命中直接置 1.0。

三条硬约束保证输出可用：

1. `priority=must` 的条款（本文档里是 `SPEC-ORD-001` 响应结构、`SPEC-ORD-030` 兼容性约束）永远入选；
2. 非 must 条款按相对得分截断（`RELATIVE_CUTOFF=0.42`），与任务无关的条款被剔除；
3. 最终按字节预算（默认 24KB）裁剪，超限条目标记 `truncated=true`。

实测两个不同任务的结果：筛选任务召回 9 条（含 `SPEC-ORD-021` 时间窗口），分页任务只召回 6 条且不含时间窗口
条款——同一份资料库，输出随任务变化，不是固定答案。

## 三项技术各自分工

**MiniMax（MiniMax-M1，经 `POST /v1/text/chatcompletion_v2`）**
承担本次代码修改的生成。三次调用各改一个文件或修一处缺陷：
`service.py` 筛选实现 → `api.py` 参数透传 → 依据目标测试失败反馈修 `invalid_range` 映射。
每次调用的 prompt 全文、响应全文、token 用量、request_id 都落在 `artifacts/logs/minimax/` 与
`artifacts/logs/minimax-devlog.jsonl`，response 的 sha256 与最终代码对应关系由 `verify_all.py` 的 B 项核对。
不采集模型私有思维链，只记录 `reasoning_present` 与长度。

**seekdb（嵌入式）**
承担工程资料的存储与检索。上下文里的每一条规格、代码、测试都来自 seekdb 查询结果，没有"读文件兜底"。
每次查询（向量查询、元数据扫描、按 id 取符号）都追加到 `artifacts/logs/seekdb-queries.jsonl`，
D 项校验比对"数据库返回的 spec id"与"上下文实际使用的 spec id"有交集。

**PowerContext 1.4.1（Server + Python Client）**
承担任务状态的保存与复用。写入用 `remember_memory`（`kind=state`），读取用 `list_memory_entries` 后按
`seq` 取最新；上下文输出的 `progress` 段即来自这里。E 项校验从空状态写入、另起进程读回、
再另起进程构造上下文三步验证，不依赖进程内变量。

## 一个刻意的工程取舍

本账号在 `api.minimax.chat` 上可用的模型是 `MiniMax-M1` / `MiniMax-Text-01`（M2.x 系列返回 2069），
且 TPM 限额约 10K。实测 `3107 prompt + 4000 max_tokens` 通过、`6000 + 8000` 触发 1039 限流。
因此 `agent/run_task.py` 提供 `--focus <文件>` 按文件分步生成：只发该文件全文 + `code_refs` 命中它的条款 +
测试断言摘要，并用 `--done` 把上一步的结论传给下一步。单次请求稳定落在 2800–4200 prompt tokens。

这不是妥协掉的正确性——目标测试与回归测试在修改前后数量一致、断言未改动，修复轮次也是由真实测试失败驱动。
它换来的是：限额之内可复现、每次调用都可审计、成本与延迟可控。

## 边界与已知限制

1. 向量由本地哈希词袋产生（384 维、确定性、无外部 embedding 服务），跨进程可复现，但不理解同义改写。
2. 代码符号粒度到类/函数，不做语句级切片；超长函数按 `_excerpt` 截断并标注。
3. 规格解析依赖 `### SPEC-` 标题与 `meta` 注释约定，不符合约定的 Markdown 不参与切分。
4. 状态采用"快照追加"，未做 Memory 合并；同一任务多次保存会累积多条 Memory，读取取 `seq` 最大者。
5. 嵌入式 seekdb 依赖 `pylibseekdb` 的平台 wheel（Windows/macOS 上的可用性见 README 的已知限制）。
