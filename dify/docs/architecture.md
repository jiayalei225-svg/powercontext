# 架构与状态机

## 1. 组件

```
┌──────────────────────────────┐
│        Dify Chatflow         │
│                              │
│ start → prep → scope →       │
│ prep_scope → recall →        │
│ engine → narrator → render → │
│ save → answer                │
└──────────┬───────────────────┘
           │ HTTP (host.docker.internal:8099)
           ▼
┌──────────────────────────────┐
│      PowerContext Server     │
│  Scope: 一个玩家一本档案       │
│  kind=save: 每回合完整存档     │
│  kind=save(status=ended):     │
│    终局 + match 摘要          │
└──────────────────────────────┘
```

- **Dify**：唯一入口、唯一编排者、唯一输出者。
- **PowerContext**：唯一持久化记忆层。每回合读一次、写一次；没有 Dify 会话变量。
- **规则引擎**：嵌入 Dify Code 节点；不访问网络、不访问文件。
- **LLM**：只负责叙事与 NPC 台词；没有事实决定权。

## 2. 节点职责

| 节点 | 输入 | 输出 | 失败时 |
|---|---|---|---|
| `start` | `sys.query`、`player_name`、`memory_id` | 同上 | — |
| `prep` | start 变量、`sys.user_id` | 清洗后的称呼、scope key | 空值兜底 |
| `scope` | scope key | `scope_id` | 默认 `{"scope_id":""}`，无记忆继续 |
| `prep_scope` | scope body | `scope_id`、`memory_ok` | 空 scope |
| `recall` | scope_id | `entries[]` | 默认空列表 |
| `engine` | query、scope_id、recall body、称呼 | scene/save/brief/answer_fallback | 内部兜底 |
| `narrator` | brief JSON、记忆摘要 | JSON 台词 | 返回空文本，render 兜底 |
| `render` | scene、LLM text、save | 最终 Markdown、存档透传 | 完整兜底 |
| `save` | scope_id、save_text | 写入结果 | 默认值，不阻断回答 |
| `answer` | render.answer | Markdown | — |

## 3. 状态机

```
                 ┌──────────────┐
                 │ role_select  │
                 └──────┬───────┘
                        │ 选身份
                        ▼
                 ┌──────────────┐
        ┌───────▶│    night     │◀───────┐
        │        └──────┬───────┘        │
        │               │ 夜晚行动/天亮    │
        │               ▼                │
        │        ┌──────────────┐        │
        │        │     day      │        │
        │        └──────┬───────┘        │
        │               │ 投票            │
        │               ▼                │
        │        ┌──────────────┐        │
        │        │  vote 结算    │────────┘
        │        └──────┬───────┘
        │               │ 猎人死亡
        │               ▼
        │        ┌──────────────┐
        │        │    hunter    │
        │        └──────┬───────┘
        │               │
        │               ▼
        │        ┌──────────────┐
        └────────│    ended     │
                 └──────────────┘

玩家出局（非猎人）→ auto_resolve → ended
```

- `day` 内部用 `chat` 计数区分“发言轮次”和“可以投票”。
- `vote` 不是独立 phase：玩家输入 `投 N` 时从 `day` 直接结算，然后进入下一夜。
- `hunter` 是玩家猎人死亡后的暂停点；AI 猎人自动开枪。
- `ended` 后输入 `再来一局` / `重开确认` 会创建新局；输入 `复盘` 展示上一局。

## 4. 记忆模型

### 4.1 每回合一份 save

```json
{
  "gid": "mf...",
  "status": "active",
  "turn": 5,
  "phase": "day",
  "day": 1,
  "players": [{"seat": 1, "role": "seer", "alive": true}],
  "relations": {"2": -2},
  "seer_checks": [...],
  "night": {...},
  "last_deaths": [4],
  "votes": {...},
  "stats": {...},
  "match": null
}
```

### 4.2 终局 save + match

```json
{
  "gid": "mf...",
  "status": "ended",
  "match": {
    "no": 1,
    "role": "seer",
    "result": "win",
    "impressions": {"2": -1, "4": 1},
    "highlight": "...",
    "post_mortem": [...]
  }
}
```

### 4.3 读取时的选择

- 按 `gid` 去重，保留 `turn` 最大的版本；
- 同 gid 的 active 旧版本会被 ended 最终版覆盖；
- active 之间按 `updated` 选最新；
- ended 按 `match.no` 排序，取最近 8 局。

这样即使每回合都写新 entry，也不会把“已经结束的局”误判为进行中。

## 5. 为什么不用 Dify 会话变量

Dify 的 `conversation_variables` 只活在一个 `conversation_id` 里。本作品的核心卖点是“换个会话还记得”，所以：

- 状态写入 PowerContext；
- 新会话只依赖 `sys.user_id` 或 `memory_id` 找到同一个 Scope；
- Dify 不需要绑定/登录，也不需要用户手动恢复。

## 6. 安全与边界

- PowerContext 无鉴权，默认只在本机/内网；
- DSL 不包含任何真实 Key；模型配置在 Dify 控制台完成；
- 引擎不执行用户输入代码；只做字符串解析和规则计算；
- LLM 输出被当作不可信数据：只提取 JSON、只接受 `speaker_plan` 内的座位、事实以引擎为准。

## 7. 可测试性

- 规则引擎是纯函数式状态机，`engine/tests/` 覆盖角色、夜晚、投票、胜负、记忆；
- DSL 由 `tools/build_dsl.py` 生成，`tools/validate_dsl.py` 做结构/变量/JSON/graphon 校验；
- `tools/simulate_workflow.py` 按 DSL 节点顺序执行，能发现变量接线错误；
- `scripts/verify.py` 做真实 PowerContext 的端到端验收。
