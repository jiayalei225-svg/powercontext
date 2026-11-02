# 验证样例与运行证据

本文给出可以按步骤执行的样例。开放式叙事不要求唯一答案；下面写的是**预期交互、规则和输出形式**，不是逐字剧本。

前置：

```powershell
cd dify
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
.venv\Scripts\python.exe scripts\seed_demo.py
```

Dify 中导入 DSL、绑定模型、确认 `POWERCONTEXT_BASE`（见 [runbook](runbook.md)）。

---

## 样例 1：预置记忆 + 中途续局（最快，建议评委先跑）

### 初始状态

- PowerContext 已启动；
- `seed_demo.py` 已执行，`memory_id=demo` 下有 3 条记录：
  - 第 1 局：玩家当狼人，狼人胜；
  - 第 2 局：玩家当预言家，狼人胜；
  - 第 3 局：进行中，玩家是预言家，第一天，昨晚验了 3 号是狼。

### 操作

1. Dify 应用开始表单：
   - 你的称呼：`演示玩家`
   - 记忆 ID：`demo`
2. 第一句输入：

   ```
   继续
   ```

3. 看到第一天场面后，输入：

   ```
   投 3
   ```

### 预期表现

- 第一句返回 **第 1 天 · 月蚀镇**，包含：
  - 你的身份：🔮 预言家；
  - 查验记录：第 1 夜 3 号 → 狼人；
  - 记忆回响：第 1 局/第 2 局的摘要，以及老周/白露等人的信任变化；
  - 场上 8 人，3 号存活；
  - 提示 `投 3`。
- 输入 `投 3` 后：
  - 返回放逐投票过程与 3 号身份；
  - 如果 3 号是狼，狼人数量减少；否则继续；
  - 进入下一夜，或直接终局。

### 证据

- PowerContext 中 `scope_id` 对应 3 条 `kind=save`；
- Dify 运行历史里 `recall` 返回这 3 条，`engine` 输出的 `phase=day`、`player_role=预言家`；
- `save` 请求体里 `text` 包含 `gid=demo-active`、`status=active`、`seer_checks`。

---

## 样例 2：跨会话 NPC 记忆（核心卖点）

### 初始状态

- 新开一个 `memory_id`（例如 `judge-demo`），或直接用 `demo` 但先不要 `继续`。

### 操作

1. 开始表单：记忆 ID 留空（按 `sys.user_id` 隔离）或填 `judge-demo`。
2. 输入 `开始游戏`，选 `狼人`。
3. 玩到终局（刀人、发言、投票；约 5–10 分钟）。
4. **新建一个会话**（不要用同一个 `conversation_id`），开始表单填**同一个记忆 ID**。
5. 输入 `开始游戏`。

### 预期表现

- 第 4 步的新会话开场出现 **「🧠 记忆回响」**：
  - `第 1 局：你当【狼人】，获胜。你当狼人骗过了整个镇子。`
  - `老周记得你坑过他（信任 -2）` 等。
- 新一局中，老周/白露的台词会更警惕；AI 投票对玩家的初始信任更低。
- 如果使用本地 shim，老周的第一句会带“又是你。上次你也这么看着我……”。

### 证据

- 两次会话使用同一个 `scope_id`；
- `recall` 节点在第二个会话返回第 1 局的 ended 存档；
- `engine.memory_digest` 包含 `第 1 局`；
- `match.impressions` 与下一局 `relations` 对应。

---

## 样例 3：完整一局（预言家）

### 操作

1. `开始游戏` → `预言家`。
2. 夜晚：`查 3`（或任意 2–8 号）。
3. 白天：输入一句自己的判断，例如 `我觉得 2 号在带节奏`。
4. `投 2`。
5. 按提示继续夜晚/白天，直到终局。

### 预期表现

- 每回合都有：
  - 当前天数/阶段；
  - 公开事件（死亡、放逐、猎人开枪）；
  - NPC 发言；
  - 只有你知道的身份/查验/药剂；
  - 场上名单与存活状态；
  - 下一步可用指令。
- 终局有：
  - 胜负；
  - 全部身份揭晓；
  - 月蚀指数、投票命中；
  - 本局记忆回响；
  - `再来一局` / `复盘` 提示。
- 玩家第一夜不会被狼人杀害。
- 玩家出局后，故事自动收束，不会停在中途。

### 规则核对

- 2 狼、1 预言家、1 女巫、1 猎人、3 村民；
- 狼人全死 → 好人胜；狼人 ≥ 好人 → 狼人胜；
- 女巫同一晚只能用一瓶药；
- 猎人被毒杀不能开枪，被刀/被放逐可以；
- 平票无人出局。

---

## 样例 4：模型失败兜底

### 操作

1. 把 LLM 节点的模型临时改成一个不可用的模型/Key，或让 shim 停掉。
2. 输入 `开始游戏` → `村民` → `天亮`。

### 预期表现

- 应用仍返回完整场景（标题、事件、身份、场上、指令）；
- 台词使用引擎模板，可能不如真实模型生动；
- 不会出现 500 / 空白回答；
- `render.llm_used=false`（可在运行历史看到）。

这说明 Dify 的流程容错和 Render 兜底生效；恢复模型后继续即可。

---

## 样例 5：PowerContext 直接核对（不经过 Dify）

```powershell
# 健康
Invoke-WebRequest http://127.0.0.1:8099/health/ready -UseBasicParsing

# 找 scope（需要知道 memory_id 或从 Dify 运行历史抄 scope_id）
.venv\Scripts\python.exe -c "import httpx,json; c=httpx.Client(base_url='http://127.0.0.1:8099'); r=c.post('/v1/memory/entries/list',json={'scope_id':'scp_xxx','limit':100}); print(len(r.json()['entries'])); print(json.dumps(r.json()['entries'][0],ensure_ascii=False)[:800])"
```

预期：

- `scope_id` 以 `scp_` 开头；
- entries 数量 ≥ 游戏回合数；
- 每条 text 是合法 JSON，含 `gid`、`status`、`players`；
- 终局条目 `status=ended` 且含 `match`。

---

## 实际运行结果

本仓库的 `evidence/` 是一次真实运行的产物（Windows 11 + Python 3.13.15 + PowerContext 1.4.1 + 本地 shim）：

| 文件 | 内容 |
|---|---|
| [`evidence/verify-transcript.md`](../evidence/verify-transcript.md) | 第一局完整对局、新会话历史战绩、新会话中途续局 |
| [`evidence/logs/verify-report.json`](../evidence/logs/verify-report.json) | 14 项断言的机器可读结果、scope_id、match 摘要 |
| [`evidence/logs/dsl-validation.txt`](../evidence/logs/dsl-validation.txt) | DSL 结构/变量/JSON/Code/graphon 校验输出 |
| [`evidence/logs/simulation-report.json`](../evidence/logs/simulation-report.json) | 两局连续模拟的报告 |

本次运行的摘要（以报告文件为准）：

| 项目 | 实际结果 |
|---|---|
| 一键验收断言 | **14 / 14 PASS** |
| 第一局 | 11 回合；玩家预言家；狼人胜；产生 `match.no=1` |
| PowerContext 存档 | 11 回合 = 11 条 `save` |
| 跨会话历史 | 新 `conversation_id` 读到「第 1 局」记忆 |
| 中途续局 | 新 `conversation_id` 续上同一 `gid`（`mfa420304df0`） |
| DSL 静态校验 | **136 / 136 PASS**；graphon 官方解析 `loadable` |
| 引擎单元测试 | **15 / 15 OK** |
| 两局连续模拟 | 15 回合，2 局都正常结束 |
| demo 档案 | 3 条记录；第三局进行中，第一天，验 3 号 = 狼人 |

> 具体回合数、胜负、scope_id 会因随机种子/模型不同而变化；报告记录的是实际值，不要求评审复现出完全相同的剧情。

---

## 恢复初始状态

### 只重置演示档案

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Moonfall\powercontext"
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
.venv\Scripts\python.exe scripts\seed_demo.py
```

### 只换一个演示身份

```powershell
.venv\Scripts\python.exe scripts\seed_demo.py --memory-id demo2
```

然后在 Dify 开始表单填 `demo2`，旧档案不动。

### 恢复 Dify 应用

DSL 导入/重新导入即可；应用不保存业务数据，所有状态在 PowerContext。

---

## 复现命令

```powershell
# 1. DSL 静态校验（结构 + 变量 + 官方 graphon 解析）
.venv\Scripts\python.exe tools\validate_dsl.py

# 2. 真实 DSL 轻量执行（一局）
.venv\Scripts\python.exe tools\simulate_workflow.py --role seer --memory-id sim-demo --games 1

# 3. 一键验收（整局 + 跨会话 + 续局）
.venv\Scripts\python.exe scripts\verify.py
```
