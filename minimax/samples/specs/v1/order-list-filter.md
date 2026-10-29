---
spec_id: order-list-filter
version: 1.0.0
status: approved
owner: order-platform
applies_to:
  - GET /orders
last_reviewed: 2026-04-03
---

# 订单列表筛选规格（v1.0.0）

本规格定义 `orderhub` 订单列表接口 `GET /orders` 的查询契约。接口需在**不破坏既有分页与排序行为**的前提下，支持按订单状态与创建时间窗口筛选。

## 1 范围

- 涉及接口：`GET /orders`
- 涉及模块：`orderhub.api`（查询串解析与错误映射）、`orderhub.service`（查询语义）
- 不在本次范围：写接口、订单状态流转、鉴权

## 2 接口契约

### SPEC-ORD-001 列表响应结构

成功响应固定为 200，body 为 JSON 对象，包含四个字段：

- `items`：订单数组，元素字段为 `id`、`customer`、`status`、`total_cents`、`created_at`、`channel`
- `total`：当前筛选条件下的记录总数（不受分页影响）
- `page`：当前页码，从 1 开始
- `page_size`：当前页大小

<!-- meta: priority=must; code_refs=src/orderhub/service.py::OrderService.list_orders,src/orderhub/api.py::handle_get_orders -->

### SPEC-ORD-010 分页参数校验

- `page` 缺省为 1，必须为正整数；非整数或小于 1 时返回 400，错误码 `invalid_pagination`。
- `page_size` 缺省为 20，取值范围 1..100（含端点）；越界返回 400，错误码 `invalid_page_size`。
- 页码超出结果范围时返回空 `items`，`total` 仍为真实总数，不得返回 404。

<!-- meta: priority=normal; code_refs=src/orderhub/service.py::OrderService.list_orders -->

### SPEC-ORD-014 状态筛选

新增查询参数 `status`，可重复出现：

- 单个 `status` 只返回该状态订单。
- 多个 `status` 按**并集**处理，等价于 SQL `IN`；重复值只计一次。
- 不传 `status` 或传空字符串时等价于不过滤。
- 允许的取值集合为：`pending`、`paid`、`shipped`、`delivered`、`cancelled`。

<!-- meta: priority=normal; code_refs=src/orderhub/api.py::handle_get_orders,src/orderhub/service.py::OrderService.list_orders -->

### SPEC-ORD-014.1 非法状态

`status` 出现取值范围外的值（例如 `refunded`）时，返回 400，错误码 `invalid_status`，`detail` 中需包含非法值，便于客户端定位。

<!-- meta: priority=normal; code_refs=src/orderhub/api.py::handle_get_orders -->

### SPEC-ORD-014.2 状态值归一化

状态比较不区分大小写，且忽略两端空白：`PAID`、` paid ` 与 `paid` 等价。归一化只影响比较，响应中的 `status` 仍返回数据中的原值（小写）。

<!-- meta: priority=normal; code_refs=src/orderhub/api.py::handle_get_orders,src/orderhub/models.py::ALLOWED_STATUSES -->

### SPEC-ORD-021 创建时间窗口

新增查询参数 `created_from` 与 `created_to`，用于按订单创建时间过滤：

- 窗口为**闭区间**：`created_from <= created_at <= created_to`。
- `created_at` 必须先归一化为 UTC 再比较；数据中的 `+08:00` 偏移不得直接按字面时间比较。
- 允许 `YYYY-MM-DD` 与完整 ISO8601（含 `Z` 或偏移）两种写法；仅给日期时，`created_from` 取当日 `00:00:00`，`created_to` 取当日 `23:59:59.999999`（UTC）。
- 两个参数可以只提供其中一个，缺省一侧表示不设边界。

<!-- meta: priority=normal; code_refs=src/orderhub/api.py::handle_get_orders,src/orderhub/service.py::OrderService.list_orders,src/orderhub/models.py::parse_iso8601 -->

### SPEC-ORD-021.1 时间参数校验

- `created_from` 晚于 `created_to` 时返回 400，错误码 `invalid_range`。
- 无法解析的时间字符串返回 400，错误码 `invalid_range`。

<!-- meta: priority=normal; code_refs=src/orderhub/api.py::handle_get_orders -->

### SPEC-ORD-024 组合筛选与总数语义

- 多个筛选条件之间为**逻辑与**关系。
- `total` 必须是应用全部筛选条件之后的记录数，而不是原始总数。
- 分页在筛选后的结果集上生效，`page`/`page_size` 语义不变。

<!-- meta: priority=normal; code_refs=src/orderhub/service.py::OrderService.list_orders -->

### SPEC-ORD-030 兼容性约束

本次修改必须保持以下既有行为，任何一项改变都视为回归缺陷：

- 排序固定为 `created_at` 降序、`id` 降序；筛选不得改变排序。
- 不带任何新参数时，`GET /orders` 的响应与修改前完全一致。
- 未知查询参数继续被忽略，不返回错误。
- 错误响应结构保持 `{"error": <code>, "detail": <detail>}`。
- `GET /orders/{id}` 与 `GET /health` 行为不变。

<!-- meta: priority=must; suite=regression; code_refs=src/orderhub/service.py::OrderService.list_orders,src/orderhub/api.py::dispatch -->

## 3 验收

功能验收由 `tests/test_order_filters.py` 覆盖；兼容性由 `tests/test_orders_pagination.py`、`tests/test_orders_sorting.py`、`tests/test_order_detail.py`、`tests/test_http_contract.py` 覆盖。两组成员集合在修改前后保持一致。
