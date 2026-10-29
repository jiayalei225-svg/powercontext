# 验收自查表

对应题面 4.1 的六项必做项。全部结论由 `python scripts/verify_all.py` 生成，
原始记录见 `artifacts/logs/verify-report.json`，每项都记录了命令、退出码与关键比对值。

## A 能够运行

通过。判定依据：

1. 从**空数据目录**执行 `python -m sddctx.cli init`，退出码 0
2. 导入计数：规格 9、代码 40、测试 35（代码数会随被测文件变化，因为被改的是同一批文件）
3. 执行 `python -m sddctx.cli context --task samples/task.json`，退出码 0
4. 输出非空：`spec_items=9`、`code_targets=12`、`tests=16`

不依赖未交付的本地文件：`.data/` 与 PowerContext 的 SQLite 都由脚本生成，
`requirements.txt` 固定了全部依赖版本。

## B MiniMax 实际参与

通过。判定依据：

1. `artifacts/logs/minimax-devlog.jsonl` 有 3 条记录，全部 `files_written` 非空
2. 模型名 `MiniMax-M1`，三个 request_id：
   `0731e7049a8b16b5687106854ee44c44`、`0731e7384e18f3c80cc66f627fb7cd23`、`0731e788d5b666b9823352d141f0cde0`
3. 开发记录里的 `src/orderhub/api.py`、`src/orderhub/service.py` 与
   `git diff HEAD~1 HEAD` 的变更文件清单有交集
4. response 内容的 sha256 与日志中的 `response_sha256` 逐个一致（文件未被事后替换）

开发记录包含：本次任务定义、发给模型的上文（规格编号清单、代码目标、测试清单、读取的工作区文件）、
模型的 `summary` 与 `spec_coverage`、token 用量、耗时、以及第三轮携带的测试失败反馈原文。

## C 上下文正确

通过。判定依据：

1. `samples/task.json` 的 `required_sources` 逐条比对，缺失项为空：
   规格 9 条、代码 2 个符号、测试 5 个用例全部在上下文中
2. 每条输出都带 `source`（规格为 `v1/order-list-filter.md#SPEC-ORD-021`，代码为
   `src/orderhub/api.py::handle_get_orders`），路径与行号可回查
3. 规格更新后使用新内容：切换到 `samples/specs/v2` 重新 `init` 后，
   `spec_version` 由 `1.0.0` 变为 `2.0.0`，`spec_digest` 变化，
   v2 独有条目 `SPEC-ORD-021.2` 出现在新上下文且 v1 上下文中不存在，
   `SPEC-ORD-024` 标题由"组合筛选与总数语义"变为含"空结果"的新版
4. 不是固定答案：换用 `samples/task_pagination.json` 后只召回 6 条规格，不含 `SPEC-ORD-021`

输出包含题面要求的四类信息：适用规格条目、需要修改的代码文件与符号、
用于验证功能及兼容性的测试（按 `functional`/`regression` 分组并标注覆盖的规格编号）、
已完成/待办/已有验证结果（`progress` 段）。

## D 数据库实际参与

通过。判定依据：

1. seekdb 三个 collection 计数均大于 0：`sddctx_spec=9`、`sddctx_code=38`、`sddctx_test=35`
2. `artifacts/logs/seekdb-queries.jsonl` 记录 100 次向量查询
3. 数据库返回的 spec 编号与上下文实际使用的 spec 编号有交集
   （`SPEC-ORD-001`、`SPEC-ORD-010`、`SPEC-ORD-014`、`SPEC-ORD-014.1`、`SPEC-ORD-014.2`、
   `SPEC-ORD-021`、`SPEC-ORD-021.1`、`SPEC-ORD-024`、`SPEC-ORD-030`）

上下文选择的候选集全部来自 seekdb 的 `query`/`get`，没有读文件兜底路径；
源文件的读取只发生在把上下文渲染成 prompt 时的"发送代码原文"一步，且文件清单本身由 seekdb 结果决定。

## E 状态能够复用

通过。判定依据（三步在不同进程里）：

1. 空状态下 `state save` 写入 `done`/`pending`/`verifications`，返回 `seq=2`
2. 另起进程 `state show` 读回，`done` 与写入内容完全一致
3. 再起进程 `context` 构造上下文，`progress.available=true`、`progress.backend="powercontext"`、
   `progress.done` 与写入一致、`verifications` 数量 ≥ 1

题面只要求"模块重启后能读取并使用保存的状态，不要求恢复完整 Agent 会话"，本实现符合该范围：
状态是结构化快照（JSON），不是会话 transcript。

## F 代码修改有效

通过。判定依据：

1. 修改前（`artifacts/before/` 的两个文件 + 同一份测试）目标测试退出码 1，
   `10 failed, 29 passed`；失败原因全部是断言不成立或"未抛异常"，
   **不存在** `ModuleNotFoundError`、`ImportError`、`ERROR collecting`、`no tests ran`
   （`verify_all.py` 显式检查这些字符串，命中则判为环境错误）
2. 修改前回归测试退出码 0
3. 修改后目标测试退出码 0（14 passed）
4. 修改后回归测试退出码 0（25 passed）；整体 `39 passed`

测试集在修改前后完全一致：`tests/` 目录未被修改，可用
`git diff <基线提交> HEAD -- minimax/sample_project/tests` 验证为空。

被测代码版本：`git_head=c95b211d57b54e542cf0c5f32904fecf190cf43c`。

## 补充说明

1. 评审从干净环境复现的推荐路径见 `README.md` 第 4 节；六项校验一条命令：
   `python scripts/verify_all.py`。
2. 未配置 `MINIMAX_API_KEY` 时，A/C/D/E/F 与全部测试仍可通过；
   只有"重新调用模型生成代码"（B 项的证据收集）需要 Key，但 B 项核对的是已提交的记录，
   不要求评审重跑模型。
3. 提交材料均在 `minimax/` 目录内：`sddctx/`（模块）、`agent/`（接入）、`sample_project/`（业务工程）、
   `samples/`（规格与任务）、`scripts/`（运行与校验）、`artifacts/`（快照/差异/日志）、`docs/`（说明）。
