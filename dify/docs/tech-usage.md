# 技术分工与调用明细

本文回答三个问题：**Dify 做了什么、PowerContext 做了什么、规则引擎做了什么**，以及评审如何核对。

---

## 1. 总览

```
玩家输入
  → Dify Start 节点（query / player_name / memory_id）
  → Code：清洗称呼，生成 scope key
  → HTTP：POST /v1/scopes               （PowerContext 建/复用玩家档案）
  → Code：解析 scope_id
  → HTTP：POST /v1/memory/entries/list  （PowerContext 读全部存档）
  → Code：月蚀镇规则引擎                  （选局、解析动作、跑规则、生成场景）
  → LLM：叙事者                           （只写氛围 + NPC 台词，输出 JSON）
  → Code：Render                         （合并台词与事实，失败时兜底）
  → HTTP：POST /v1/memory/remember      （PowerContext 写回本回合存档）
  → Answer：输出
```

**Dify** 承担全部编排、HTTP 调用、LLM 调用、条件容错和输出；**PowerContext** 承担跨会话的“我是谁、我干过什么、NPC 怎么看我”；**规则引擎**（在 Dify Code 节点内）承担确定性狼人杀规则。

---

## 2. Dify：10 个节点

DSL：[`dsl/moonfall-werewolf.chatflow.yml`](../dsl/moonfall-werewolf.chatflow.yml)

| 节点 ID | 类型 | 作用 | 关键输入/输出 |
|---|---|---|---|
| `start` | start | 收集聊天输入与两个可选变量 | `player_name`、`memory_id`、`sys.query` |
| `prep` | code | 清洗称呼；生成 `moonfall:user:<key>` | 输出 `player`、`memory_id`、`scope_key` |
| `scope` | http-request | 创建/复用 PowerContext Scope | `POST /v1/scopes`，幂等键 `scope_key` |
| `prep_scope` | code | 解析 `scope_id`，失败时允许无记忆继续 | `scope_id`、`memory_ok` |
| `recall` | http-request | 读取该玩家全部存档 | `POST /v1/memory/entries/list`，limit 100 |
| `engine` | code | **核心规则引擎**：加载存档、解析动作、夜晚/白天/投票/胜负、生成场景与存档 | `scene_json`、`save_text`、`brief_json`、`answer_fallback` |
| `narrator` | llm | 叙事者：氛围 + 指定 NPC 台词，严格 JSON | `narrator.text` |
| `render` | code | 合并 LLM 台词与引擎事实；模型抽风时用完整兜底 | `answer`、`save_text`、`llm_used` |
| `save` | http-request | 写回本回合完整存档 | `POST /v1/memory/remember`，kind=`save` |
| `answer` | answer | 输出 Markdown | `render.answer` |

### 2.1 Dify 能力对应

| Dify 能力 | 在作品中的使用 |
|---|---|
| Start 变量 | `player_name`（称呼）、`memory_id`（演示档案/跨浏览器身份） |
| Code 节点 | 3 段 Python：输入清洗、规则引擎、LLM 输出合并；规则引擎约 60 KB，由 `tools/build_dsl.py` 从 `engine/moonfall.py` 自动嵌入 |
| HTTP Request | 3 次外部调用：建 Scope、读记忆、写存档；全部设置 `error_strategy: default-value` |
| LLM | 1 次/回合，temperature 0.9，严格 JSON 约束；只负责“氛围与台词”，不决定事实 |
| Answer | 直接输出引擎 + LLM 合并后的 Markdown |
| 环境变量 | `POWERCONTEXT_BASE`，评审无需改节点即可换地址 |
| 会话窗口 | LLM `memory.window.size=6`，保留最近对话的语气连续性 |

### 2.2 为什么把规则放在 Code 节点

- 狼人杀的死亡、投票、胜负必须确定性，不能让 LLM 编；
- Dify Code 节点可以执行标准库 Python，适合把状态机放在编排内部，Dify 仍然是核心流程 owner；
- 规则引擎同时被本地测试、DSL 生成器、验收脚本复用，避免“DSL 里一份、文档里一份”。

### 2.3 LLM 失败时会发生什么

`render` 节点会尝试从 LLM 输出中提取第一个 JSON 对象；如果失败：

- 使用 `engine.scene_json` 里的兜底叙事和模板台词；
- 保留所有事实、私密信息、行动提示；
- `llm_used=false`，但玩家仍能继续游戏。

因此模型不稳定不会阻断流程。

---

## 3. PowerContext：记忆与上下文

- 版本：`powercontext[server]==1.4.1`，SQLite 后端，官方 HTTP API。
- 启动：`scripts/run_powercontext.py`，默认 `0.0.0.0:8099`。
- 数据：Windows `%LOCALAPPDATA%\Moonfall\powercontext\powercontext.sqlite3`；Linux `~/.local/share/moonfall/powercontext/`。

### 3.1 Scope：一个玩家一本档案

```http
POST /v1/scopes
Content-Type: application/json

{
  "title": "月蚀镇·狼人杀玩家档案",
  "summary": "保存玩家在月蚀镇的每一局身份、胜负、NPC 关系与对局存档，供跨会话续局和 NPC 记忆复用。",
  "idempotency_key": "moonfall:user:<memory_id 或 Dify sys.user_id>"
}
```

- 同一个 `idempotency_key` 重复调用返回同一个 `scope_id`（实测 201 + 相同 id），所以不需要登录/绑定流程。
- `memory_id` 留空时使用 Dify 的 `sys.user_id`，同一浏览器跨会话稳定；填 `demo` 则使用预置档案。
- 不同玩家自动隔离。

### 3.2 读记忆

```http
POST /v1/memory/entries/list
Content-Type: application/json

{"scope_id": "scp_xxx", "limit": 100}
```

返回 `entries[]`，每条包含 `kind`、`text`、`state`、`artifact` 等。`text` 是引擎写入的 JSON 存档。

引擎的解析逻辑（`engine/moonfall.py` 的 `_parse_memory`）：

1. 只接受能解析成 JSON、且含 `gid` / `players` 的 text；
2. 按 `gid` 去重，保留 `turn` 最大的一份（结束局会保留 status=ended 的最终版）；
3. `status=active` 的存档按 `updated` 选最新 → 用于跨会话续局；
4. `status=ended` 的存档收集 `match` → 用于历史战绩与 NPC 关系。

### 3.3 写存档

```http
POST /v1/memory/remember
Content-Type: application/json

{
  "scope_id": "scp_xxx",
  "kind": "save",
  "text": "{...完整状态 JSON...}",
  "reason": "月蚀镇自动存档 <gid> / turn <n>"
}
```

每回合写一份，`kind` 固定 `save`。`text` 同时包含：

- 当前牌局状态（`status=active`）；
- 或终局状态 + `match` 摘要（`status=ended`）。

单条 text 控制在 8 KB 以内（PowerContext 上限 8192 UTF-8 bytes），引擎的 `_compact_state` 会在超限时裁剪日志/旧查验。

### 3.4 存档 schema（简化）

```json
{
  "v": 1,
  "gid": "mf...",
  "status": "active",
  "created": 1760000000.0,
  "updated": 1760000000.0,
  "turn": 4,
  "phase": "day",
  "day": 1,
  "match_no": 3,
  "player_name": "演示玩家",
  "players": [
    {"seat": 1, "role": "seer", "alive": true, "claim": "", "revealed": false},
    {"seat": 2, "role": "wolf", "alive": true, "claim": "", "revealed": false}
  ],
  "relations": {"2": -2, "3": 1},
  "heat": {"1": 0.22, "2": 0.4},
  "witch": {"antidote": true, "poison": true},
  "seer_checks": [{"by": 1, "day": 1, "seat": 3, "result": "狼人"}],
  "night": {"victim": 4, "wolf_target": 4, "saved": false, "poison": 0, "resolved": true},
  "last_deaths": [4],
  "votes": {"1": 3, "2": 3},
  "last_vote": {"day": 1, "votes": {"1": 3}, "exiled": 3, "tie": false},
  "claims": [],
  "chat": 1,
  "log": ["..."],
  "stats": {"lies": 0, "correct_votes": 1, "wrong_votes": 0, "defended": [], "accused": [3]},
  "match": null
}
```

终局时 `status=ended`，并追加：

```json
{
  "match": {
    "no": 3,
    "role": "seer",
    "winner": "good",
    "result": "win",
    "days": 3,
    "player_alive": true,
    "betrayed": [2, 3],
    "defended": [4],
    "impressions": {"2": -1, "3": -1, "4": 1, "5": 0, "6": 0, "7": 0, "8": 0},
    "highlight": "你活到了最后，狼人被清出月蚀镇。",
    "eclipse": 73,
    "quote": "月蚀镇不记仇，它只记账。",
    "post_mortem": ["第 2 夜：..." ]
  }
}
```

### 3.5 NPC 关系如何复用

- 每局结束，引擎按“玩家指认/投票/保护过谁、是否骗人、是否获胜”计算每个 NPC 的 `impressions`（-3..+3）。
- 下一局开始时，`_relations_from_matches` 把历史 impressions 累加为 `relations`。
- 关系值进入 AI 投票评分（信任低更容易投你）和 LLM 的 `memory_digest`（“老周记得你坑过他（信任 -2）”）。
- 所以“记仇”不是一句台词，而是会影响下一次投票倾向的真实状态。

### 3.6 跨会话续局

1. 每回合 `save` 都写 `status=active` + `updated`；
2. 新会话没有 Dify 会话变量，但有同一个 Scope；
3. `recall` 拉回所有存档，`_parse_memory` 选 `updated` 最新的 active；
4. 玩家输入 `继续` 或 `开始游戏`，引擎直接展示当前 `phase` 的场景。

这就是为什么应用不依赖 Dify 的 `conversation_variables`：**状态在 PowerContext，不在浏览器会话里**。

### 3.7 核对方式

```bash
# 健康
curl -s http://127.0.0.1:8099/health/ready

# 看某个 scope 的所有记忆
curl -s -X POST http://127.0.0.1:8099/v1/memory/entries/list \
  -H "Content-Type: application/json" \
  -d '{"scope_id":"scp_xxx","limit":100}'
```

也可以直接看 Dify 运行历史里 `scope`、`recall`、`save` 三个 HTTP 节点的请求体/响应体；`save` 的 `text` 里能看到完整 `gid`、`phase`、`match`。

一键验收：`python scripts/verify.py` 会把 Scope、每回合存档、ended match、跨会话记忆、中途续局全部断言并写入 `evidence/`。

---

## 4. 规则引擎：确定性地玩

`engine/moonfall.py` 是一个不依赖网络的纯 Python 状态机，约 60 KB，被原样嵌入 `engine` Code 节点。

### 4.1 角色与阵容

- 8 人：玩家 + 7 NPC；
- 2 狼人、1 预言家、1 女巫、1 猎人、3 村民；
- 玩家可选任意角色，剩余角色洗牌分配给 NPC。

### 4.2 流程

```
role_select → night → day（发言/投票）→ night → ... → ended
                     ↘ hunter（猎人开枪）
                     ↘ auto_resolve（玩家出局后自动收束）
```

- **夜晚**：狼人刀人；预言家查验；女巫救/毒；猎人被刀可开枪（被毒不能）。
- **白天**：玩家自由发言；引擎解析“我是预言家 / X 是狼 / 我保 X / 投 X”等意图，更新热度与关系；NPC 发言由 LLM 按 `speaker_plan` 生成。
- **投票**：每个活着的玩家一票；平票无人出局；放逐公开身份；猎人被放逐可开枪。
- **胜负**：狼人全死 → 好人胜；狼人数量 ≥ 好人数量 → 狼人胜。
- **玩家出局**：非猎人会进入自动收束，AI 继续把夜晚/投票跑到胜负，输出上帝视角终局，避免“死了就没得玩”。

### 4.3 随机性

所有随机决策由 `sha256(状态 + 动作 + 座位)` 派生，不依赖进程随机数。同一个存档 + 同一个输入会得到同一个结果，方便复盘和测试。

---

## 5. 为什么没有 seekdb

题目明确允许 **seekdb 或 PowerContext 至少一种**。本作品：

- 选择 PowerContext 承担记忆/上下文；
- 没有把 Dify 自带的 PostgreSQL 说成 seekdb；
- 没有为了凑技术栈额外引入 seekdb；
- PowerContext 的 SQLite 后端只是它自己的存储实现，不是本作品的技术结合点。

如果评审希望看到 seekdb 版本，可把 PowerContext 的 `database` 配置换成 seekdb/OceanBase 后端（PowerContext 支持 OceanBase 存储），但本提交未声明、未验证该路径，因此不作为交付内容。

---

## 6. 复现与证据

| 材料 | 位置 |
|---|---|
| DSL | `dsl/moonfall-werewolf.chatflow.yml` |
| 规则引擎源码 | `engine/moonfall.py` |
| 渲染器源码 | `engine/render.py` |
| DSL 生成器 | `tools/build_dsl.py`（修改引擎后重新生成，避免 DSL 与源码漂移） |
| DSL 校验 | `tools/validate_dsl.py`（含 Dify 1.17 graphon 官方解析） |
| 真实 DSL 执行器 | `tools/simulate_workflow.py` |
| 一键验收 | `scripts/verify.py` |
| 实际运行记录 | `evidence/verify-transcript.md`、`evidence/logs/verify-report.json` |
| 演示档案 | `scripts/seed_demo.py` |

评审可以只信 Dify 运行历史 + PowerContext API 返回；`verify.py` 只是把同样的链路自动化，方便快速核对。
