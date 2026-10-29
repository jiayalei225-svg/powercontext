# 验证样例说明

## 一句话

在示例工程 `orderhub` 上，把 `GET /orders` 从"只支持分页"改成"支持按订单状态与创建时间窗口筛选"，
过程中由 `sddctx` 提供规格、代码与测试，由 MiniMax 生成代码，验证结果写入 PowerContext。

## 要改什么

新增三个查询参数，并保持既有分页与排序语义不变。

1. `status`：可重复出现，多值并集；取值限定 `pending`/`paid`/`shipped`/`delivered`/`cancelled`；
   非法值返回 400 且错误码 `invalid_status`；比较不区分大小写、忽略两端空白。
2. `created_from` / `created_to`：闭区间；按 UTC 归一化后比较；支持 `YYYY-MM-DD` 与完整 ISO8601；
   `created_from` 晚于 `created_to`、或时间无法解析时返回 400 且错误码 `invalid_range`。
3. 组合筛选为逻辑与；`total` 为筛选后总数；分页在筛选结果集上生效。

涉及的代码文件与符号：

- `src/orderhub/service.py` 的 `OrderService.list_orders`（筛选、排序、分页语义）
- `src/orderhub/api.py` 的 `handle_get_orders`（查询串解析与错误映射）

## 哪些原有行为必须保持

对应规格 `SPEC-ORD-030`（兼容性约束），任何一条改变都算回归缺陷：

1. 排序固定为 `created_at` 降序、`id` 降序，筛选不得改变排序。
2. 不带任何新参数时，`GET /orders` 的响应与修改前完全一致。
3. 未知查询参数继续被忽略，不返回错误。
4. 错误响应结构保持 `{"error": <code>, "detail": <detail>}`。
5. `GET /orders/{id}` 与 `GET /health` 行为不变。

## 上下文中必须出现的来源

这些编号与路径可直接在 `artifacts/context/context.json` 中核对，`samples/task.json` 的
`required_sources` 字段是机器可读版本，`scripts/verify_all.py` 的 C 项会逐条比对缺失项。

有效规格条目（9 条，全部来自 `samples/specs/v1/order-list-filter.md`）：

1. `SPEC-ORD-001` 列表响应结构（priority=must）
2. `SPEC-ORD-010` 分页参数校验
3. `SPEC-ORD-014` 状态筛选
4. `SPEC-ORD-014.1` 非法状态
5. `SPEC-ORD-014.2` 状态值归一化
6. `SPEC-ORD-021` 创建时间窗口
7. `SPEC-ORD-021.1` 时间参数校验
8. `SPEC-ORD-024` 组合筛选与总数语义
9. `SPEC-ORD-030` 兼容性约束（priority=must，suite=regression）

必要代码来源（必须命中，均为 `路径::符号` 形式）：

1. `src/orderhub/api.py::handle_get_orders`
2. `src/orderhub/service.py::OrderService.list_orders`

必要测试来源（上下文必须包含这些用例）：

1. `tests/test_order_filters.py::test_filter_single_status`（覆盖 SPEC-ORD-014）
2. `tests/test_order_filters.py::test_filter_multiple_statuses_is_union`（SPEC-ORD-014）
3. `tests/test_order_filters.py::test_unknown_status_rejected`（SPEC-ORD-014.1）
4. `tests/test_order_filters.py::test_reversed_window_rejected`（SPEC-ORD-021.1）
5. `tests/test_orders_pagination.py::test_default_page_size_is_20`（SPEC-ORD-030，回归）

## 初始数据

`sample_project/data/orders.json`：16 条订单，覆盖 5 种状态、4 个渠道、跨 3 月与 4 月，
其中 `ORD-1002`、`ORD-1005`、`ORD-1008`、`ORD-1011`、`ORD-1014` 使用 `+08:00` 偏移，
用于验证 UTC 归一化（`ORD-1008` 的 `2026-03-10T07:45:00+08:00` 等于 `2026-03-09T23:45:00Z`）。

## 操作步骤

工作目录 `minimax/`，先启动 PowerContext Server 并初始化资料：

```
python scripts/run_powercontext.py --data-dir .data/powercontext --port 8099   # 终端 1
python -m sddctx.cli init                                                       # 终端 2
```

生成上下文并查看必要来源是否齐全：

```
python -m sddctx.cli context --task samples/task.json --out artifacts/context/context.json
python scripts/verify_all.py --only C
```

要让 MiniMax 重新生成一次代码修改（会覆盖 `sample_project` 的两个源文件）：

```
python -m agent.run_task --task samples/task.json --attempt 1-service --focus src/orderhub/service.py
python -m agent.run_task --task samples/task.json --attempt 2-api --focus src/orderhub/api.py \
  --done "service.py 已实现筛选，签名为 list_orders(*, page, page_size, status, created_from, created_to)"
```

跑测试并记录：

```
cd sample_project && python -m pytest -q && cd ..
python scripts/record_tests.py
```

## 预期结果

1. `python -m sddctx.cli init`：规格 9 条、代码符号 38–40 个、测试用例 35 个写入 seekdb 三个 collection；
   PowerContext 返回 `ok=true` 并创建/复用 Scope。
2. `context` 输出：`spec_version=1.0.0`，`spec_items` 9 条，`code_targets` 命中上述两个必要符号，
   `tests.functional` 含 4 个目标用例、`tests.regression` 含回归用例，`progress.available=true`。
3. 把规格换成 v2 重新 `init`：`spec_version` 变为 `2.0.0`、`spec_digest` 变化，
   出现 v2 独有的 `SPEC-ORD-021.2`，`SPEC-ORD-024` 标题变为含"空结果"的新版。
4. 目标测试：修改前 `10 failed, 29 passed`（全部是断言失败或未抛错，无导入/收集错误）；
   修改后 `39 passed`（目标 14 + 回归 25）。
5. `scripts/verify_all.py`：A–F 六项全 `PASS`，退出码 0。

## 如何重置

1. 只重置索引与状态缓存：`python scripts/reset_data.py`（删除 `.data/`）。
2. 同时重置 PowerContext 里的 Scope 与 Memory：停掉 Server，删除其 `--data-dir` 目录，重新启动。
3. 还原代码到修改前：用 `artifacts/before/src/orderhub/` 覆盖 `sample_project/src/orderhub/` 同名文件，
   或 `git checkout <基线提交> -- minimax/sample_project/src/orderhub/`。

## 与"固定答案"的区别

同一份资料库上，把任务换成 `samples/task_pagination.json`（只涉及分页校验）后，上下文只召回 6 条规格，
不包含 `SPEC-ORD-021` 时间窗口条款；两个任务的 `spec_digest` 不同。C 项校验与
`tests_sddctx/test_selector.py::test_irrelevant_specs_are_dropped` 都覆盖了这一点。
