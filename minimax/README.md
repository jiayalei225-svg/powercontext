# SDD 工程上下文模块（MiniMax × OceanBase / PowerContext）

「规有所依」——为 AI 开发助手提供一次真实代码修改所需的**规格、代码、测试**，
把任务进展存到 PowerContext，并用 MiniMax 完成代码修改。

本目录是参赛作品的完整交付物：上下文模块源码、示例业务工程、验证样例、
代码差异、测试日志与技术使用记录。

## 1. 目录结构

- `sddctx/`：上下文模块（资料导入、seekdb 检索、上下文组装、状态读写、CLI/HTTP 入口）
- `agent/`：开发助手接入层（MiniMax 客户端 + 任务编排 + 开发日志）
- `sample_project/`：示例业务工程 `orderhub`（可运行、有测试，本次修改的落点）
- `samples/specs/v1/`、`samples/specs/v2/`：规格基线与其更新版（用于验证"规格更新后使用新内容"）
- `samples/task.json`：验证样例的任务定义（含必须出现在上下文中的来源清单）
- `samples/task_pagination.json`：对照任务（证明上下文不是固定答案）
- `scripts/`：启动 PowerContext、生成上下文快照、一键校验、重置数据
- `artifacts/before/`、`artifacts/after/`、`artifacts/diff/`：修改前后代码快照与差异
- `artifacts/context/`：交付用上下文输出
- `artifacts/logs/`：MiniMax 开发记录、seekdb 查询记录、测试日志、校验报告
- `docs/architecture.md`：一页技术说明（模块结构、上下文选择方式、三项技术分工）
- `docs/verification-sample.md`：验证样例说明（要改什么、必须保持什么、必要来源、初始数据、步骤、预期、重置）
- `docs/tech-usage.md`：技术使用记录（MiniMax / seekdb / PowerContext 的实际接入与调用明细）
- `docs/acceptance-checklist.md`：六项必做项的验收自查表

## 2. 依赖与版本

Python 3.11 及以上（实测 Windows 11 + Python 3.13.12、Linux + Python 3.12）。

安装：

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS 用 .venv/bin/python
```

关键依赖（版本固定，见 `requirements.txt`）：

- `powercontext[cli,server]==1.4.1`：任务状态与记忆（PowerContext Server + Python Client）
- `pyseekdb==1.4.0.post1`：seekdb Python SDK，使用**嵌入式**模式
- `pylibseekdb==1.4.0.post2`：嵌入式 seekdb 引擎（Windows/Linux 均有 wheel）
- `httpx`、`pytest`

说明：`pyseekdb` 的嵌入式模式在缺少 `pylibseekdb` 时会提示只能连远程 Server。
本作品显式依赖 `pylibseekdb`，因此评审环境无需另起数据库进程。

## 3. 配置

复制 `.env.example` 为 `.env` 并填写（`.env` 已被 `.gitignore` 忽略，不会进仓库）：

- `MINIMAX_API_KEY`：MiniMax 开放平台 API Key（必填，仅在重新调用模型时需要）
- `MINIMAX_BASE_URL`：默认 `https://api.minimax.chat/v1`（国内区；海外区为 `https://api.minimaxi.chat/v1`）
- `MINIMAX_MODEL`：默认 `MiniMax-M1`
- `MINIMAX_MAX_TOKENS`：单次输出上限，默认 24000（实际会按 TPM 预算下调，见第 5.4 节）
- `SDDCTX_POWERCONTEXT_URL`：默认 `http://127.0.0.1:8099`
- `SDDCTX_BUDGET_BYTES`：上下文预算，默认 24000 字节

环境变量优先级高于 `.env`：`sddctx.config` 会读取 `minimax/.env`，
但只在对应变量未设置时填充，不会覆盖 shell 中已有的值。

关于模型名：`MiniMax-M2.x` 系列在 `api.minimax.chat` 上返回 `code 2069`（no longer available），
该账号可用的文本模型为 `MiniMax-M1` 与 `MiniMax-Text-01`。切换模型只需改 `MINIMAX_MODEL`。

## 4. 快速开始（评审复现路径）

以下命令的工作目录均为 `minimax/`。

第 1 步，启动 PowerContext Server（占一个终端，保持运行）：

```
python scripts/run_powercontext.py --data-dir .data/powercontext --port 8099
```

第 2 步，初始化工程资料（写入 seekdb，并创建 PowerContext Scope）：

```
python -m sddctx.cli init
```

预期输出：`ingested.specs=9`、`ingested.code>0`、`ingested.tests>0`，
`seekdb.collections` 三个 collection 计数大于 0，`powercontext.ok=true`。

第 3 步，为验证样例构造开发上下文：

```
python -m sddctx.cli context --task samples/task.json --out artifacts/context/context.json
```

第 4 步，运行六项必做项校验：

```
python scripts/verify_all.py
```

全部通过时退出码为 0，逐项结论写入 `artifacts/logs/verify-report.json`。

第 5 步（可选），重新用 MiniMax 走一遍代码修改：

```
python -m agent.run_task --task samples/task.json --attempt 1-service --focus src/orderhub/service.py
python -m agent.run_task --task samples/task.json --attempt 2-api --focus src/orderhub/api.py \
    --done "service.py 已实现筛选，签名为 list_orders(*, page, page_size, status, created_from, created_to)"
```

注意：该命令会用模型输出覆盖 `sample_project/src/orderhub/*.py`，
仅在你想复现"模型改代码"过程时使用；评测代码结果请直接跑测试。

### 5.4 为什么按文件分步生成

该 MiniMax 账号的 TPM 限额约 10K（实测 `3107 prompt + 4000 max_tokens` 通过，`6000 + 8000` 触发
`1039 rate limit exceeded(TPM)`）。因此 `agent/run_task.py` 提供 `--focus <文件>`：
只发送目标文件全文 + `code_refs` 命中该文件的规格条款 + 测试断言摘要，
并用 `--done` 把上一步结论传给下一步。单次请求稳定落在 2800–4200 prompt tokens。

`--feedback-file <路径>` 可把测试失败摘要附进 prompt，让模型针对失败修复（真实开发中用过一轮）。

## 5. 调用入口与输入输出

### 5.1 CLI

- `python -m sddctx.cli init`：建库并导入规格/代码/测试；输入为工程目录，输出为导入计数与 seekdb 统计
- `python -m sddctx.cli ingest [specs|code|tests]`：重新导入指定资料（`specs` 为全量替换）
- `python -m sddctx.cli context --task <文件或内联 JSON>`：核心入口，输出任务上下文 JSON
- `python -m sddctx.cli state show --task-id <ID>`：从 PowerContext 读取任务状态
- `python -m sddctx.cli state save --task-id <ID> --file <JSON>`：写入任务状态
- `python -m sddctx.cli stats`：查看 seekdb 与 PowerContext 状态
- `python -m sddctx.cli serve --port 8123`：以 HTTP 方式暴露

全局参数 `--specs-dir`、`--project-root` 需写在子命令之前，例如：

```
python -m sddctx.cli --specs-dir samples/specs/v2 init
```

### 5.2 HTTP（供 Agent 插件/MCP 桥接）

- `POST /context`：请求体同 `samples/task.json`，返回同一份上下文 JSON
- `GET /stats`、`GET /health`

### 5.3 上下文输出契约

顶层字段：

1. `task_id`、`generated_at`
2. `spec_version`、`spec_digest`：本次使用的规格版本与摘要（规格更新后必然变化）
3. `spec_items[]`：`id`、`title`、`source`（文件#条目号）、`lines`、`text`、`priority`、`suite`、
   `code_refs`（该条款引用的代码符号）、`score`、`match`
4. `code_targets[]`：`path`、`symbol`、`kind`、`lines`、`signature`、`source`、`score`、`reason`、`excerpt`
5. `tests.functional[]` / `tests.regression[]`：`id`、`path`、`lines`、`covers`（覆盖的规格条目）、`source`、`score`、`suite`
6. `progress`：`available`、`backend`、`done`、`pending`、`verifications`（来自 PowerContext）
7. `metrics`：候选/选中数量、字节数、是否截断、耗时
8. `seekdb`：后端、三个 collection 计数、本次查询次数

`source` 一律为真实文件路径（规格带条目号，代码带符号名），可直接回查。

## 6. 测试

业务工程测试（工作目录 `sample_project/`）：

```
python -m pytest -q
```

分组：

- 目标功能测试：`tests/test_order_filters.py`（修改前失败、修改后通过）
- 回归测试：`tests/test_orders_pagination.py`、`tests/test_orders_sorting.py`、
  `tests/test_order_detail.py`、`tests/test_http_contract.py`（修改前后都必须通过）

上下文模块自身测试（工作目录 `minimax/`）：

```
python -m pytest -q tests_sddctx
```

## 7. 数据初始化与重置

- 初始化：`python -m sddctx.cli init`（幂等，规格/代码/测试按类全量重建）
- 重置：`python scripts/reset_data.py`（删除 `.data/`，即 seekdb 数据与 Scope 缓存）
- 彻底重置状态服务：停止 Server 后删除其 `--data-dir`，再重新启动

## 8. 已知限制

1. 上下文模块使用**本地哈希向量**（384 维，无外部 embedding 服务），
   语义泛化能力弱于学习型 embedding；中文以字二元组切分，跨领域稳定但不理解同义改写。
2. seekdb 嵌入式写入后必须调用 `refresh_index()` 才可检索，否则 `query` 返回空结果集；
   导入耗时随资料量线性增长，当前样例规模（规格 9 条、代码 38–40 个符号、测试 35 个用例）下单次导入约 10 秒。
3. 代码符号粒度到"类/函数"，不做语句级切片；超长函数会被预算截断（`excerpt` 标注）。
4. 规格解析依赖约定：条目以 `### SPEC-XXX-000 标题` 起头，元数据写在
   `<!-- meta: priority=...; code_refs=...; suite=... -->` 注释里。不符合约定的 Markdown 不会被切分。
5. 任务状态以"快照追加"方式写入 PowerContext（每保存一次新增一条 Memory），
   读取时取 `seq` 最大者；未做 Memory 合并。
6. Windows 下 `pyseekdb` 嵌入式需要 `pylibseekdb` 的 win_amd64 wheel；
   macOS 若取不到 wheel，需改用远程 seekdb Server（`pyseekdb.Client(host=..., port=...)`）。
7. 评审复现时若未配置 `MINIMAX_API_KEY`，第 1–4 步与全部测试仍然可跑通；
   只有第 5 步（重新调用模型生成代码）需要 Key。
8. 该 MiniMax 账号 TPM 约 10K，单次请求无法承载"全部规格 + 全部代码 + 全部测试"，
   因此代码修改采用 `--focus` 按文件分步生成（见 5.4）。若换成限额更高的账号，
   可以去掉 `--focus` 一次性生成多个文件。
