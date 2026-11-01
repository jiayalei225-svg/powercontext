# 验收手册 · StudyCoach

本文件是给评审、也给未来的自己看的：如何从零启动、每一步应该看到什么、哪些数字会随状态变化、截图对应哪个功能。

> 本机复现环境：Windows 11 · Python 3.13 · 嵌入式 seekdb · PowerContext 1.4.1 · BGE-small-zh-v1.5（512 维）。首次运行需要网络下载依赖与模型。

---

## 0. 前置与干净数据

### 启动

```bat
:: Windows
start_windows.bat
```

```bash
# macOS
./start_macos.sh
```

脚本会按 **app → PowerContext** 的顺序启动。若手动启动，务必先让 `http://127.0.0.1:8090/health` 正常，再运行 `scripts/start_powercontext.*`。原因见 README「故障排查」。

### 重置到干净状态（可选）

停掉两个服务后删除运行时目录（不要删 `data/models/`，否则要重新下载模型）：

```bash
rm -rf data/seekdb data/powercontext data/uploads
```

```bat
rmdir /s /q data\seekdb data\powercontext data\uploads
```

重启后 `GET /health` 应显示 `documents=0, chunks=0, knowledge_points=0`、记忆 0 条。

---

## 1. 自动验收（推荐先跑）

```bash
cd qoder
.venv/Scripts/python.exe scripts/verify.py      # Windows
# .venv/bin/python scripts/verify.py            # macOS
```

脚本只用标准库，按 11 步请求真实 HTTP 接口，最后输出 `ALL PASS` 并以退出码 0 结束。它 **会写入数据**（一次导入、两轮问答、一次收尾、3 道练习、一份计划），这是验收的一部分，不是只读检查。

### 实际输出（2026-11-01，节选）

```
[1. 健康检查]
  PASS  应用返回 ok · stage=S6
  PASS  seekdb 已连接
  PASS  PowerContext ready
  PASS  本地嵌入可用 · bge-small-zh-v1.5 · 512d

[2. 导入种子资料（幂等）]
  PASS  文档已入库 · 3 份 · 本次跳过 3
  PASS  chunk 已建索引 · 27 chunks

[3. 混合检索与引用契约]
  PASS  返回检索结果 · 5 条 · hybrid · keywords=['正则化', '过拟合', '关系']
  PASS  每条结果带引用字段 · chunk_id, doc_id, doc_title, section, page
  PASS  检索写入 trace · tr_612617053cb34e21

[4. 第一轮问答（seekdb + PowerContext 同时调用）]
  PASS  回答模式明确 · evidence
  PASS  回答引用了 seekdb 结果 · 5 条引用
  PASS  有 seekdb trace
  PASS  有记忆 trace

[5. 会话收尾写回记忆]
  PASS  收尾写入记忆 · 本次新增 1 条 · ['session_summary']
  PASS  会话摘要存在
  PASS  薄弱点存在 · 相同卡点按幂等复用
  PASS  偏好存在 · 相同偏好按幂等复用
  PASS  收尾轨迹覆盖两层 · {'seekdb': 5, 'powercontext': 6, 'app': 2}

[6. 第二轮问答（跨会话记忆注入）]
  PASS  注入了跨会话记忆 · 10 条 · ['profile', 'session_summary', 'task_state', 'weakness']
        first memory: [profile] 先给一句话结论，再配一个中文例子

[7. 记忆列表]
  PASS  记忆可列出 · 32 条 · ['plan', 'profile', 'session_summary', 'task_state', 'weakness']

[8. 今日复习队列]
  PASS  队列非空 · 10 个 · due=14

[9. 出题、判分与掌握度]
  PASS  由原文生成题目 · 3 题 · {'queue': 3, 'new': 3, 'knowledge_points': 27}
  PASS  结果含掌握度与出处 · mastery 0.5 → 0.4
  PASS  练习进展写入 PowerContext · ['task_state', 'weakness']
  PASS  答错写入错因记忆 · 错 2 题

[10. 学习计划写入与复用]
  PASS  计划写入 PowerContext · art_86ff604c456943d8b3206f93a324a064
  PASS  重复生成复用同一条 · art_86ff... == art_86ff...

[11. 技术轨迹分层]
  PASS  有 seekdb 轨迹
  PASS  有 PowerContext 轨迹
  PASS  有应用轨迹 · ['app', 'powercontext', 'seekdb']

============================================================
ALL PASS · 问答、记忆、复习、计划与轨迹均已跑通
```

### 说明

- **数字会变**：`due`、记忆条数、今日已答数取决于之前跑过多少次；结构化断言（字段、trace、记忆 kind、计划复用）不受影响。
- **幂等是预期行为**：重复运行不会重复写同样的 weakness / profile，脚本会显示“相同卡点按幂等复用”并通过。
- 若某一步失败，脚本会指出是健康检查、检索、记忆、判分还是计划，并给出 HTTP 错误正文。

---

## 2. 手工 UI 验收（10 分钟）

### 2.1 资料入库

1. 打开 `http://127.0.0.1:8090`。
2. 进入 **资料库** → 点 **导入示例资料**。
3. 预期：3 份文档（机器学习基础讲义 12 chunks、线性代数核心讲义 11 chunks、我的手写复习笔记 4 chunks），统计卡显示 **3 文档 / 27 chunks / 3 学科 / 512 维**。
4. 再点一次导入：应提示已存在、全部跳过，chunk 数不变。

上传测试：拖一个 `.md` 或 `.txt`，填写学科，点 **上传并索引**；文档列表出现新行。删除后 chunk 数下降、知识点重建。

### 2.2 问答与引用

1. 进入 **问答**，问题输入：`正则化和过拟合是什么关系？`，模式 **混合**。
2. 点发送。预期：
   - 回答先给结论，再列 1–2 条原文，引用带方括号编号；
   - 下方引用卡片显示文档、章节、页码、相似度；
   - 右上角“技术轨迹”数字增加。
3. 打开技术轨迹抽屉：能看到 `seekdb / search` 与 `powercontext / search_memory`、`build_context`。

### 2.3 会话收尾写记忆

1. 在答案卡点 **结束本轮 · 写入记忆**。
2. 填写：卡点 `L1 和 L2 的区别总是记反`；偏好 `先给一句话结论，再配一个中文例子`。
3. 提交后预期：toast 提示写入 N 条记忆；左侧“本轮从 PowerContext 注入的记忆”在下一轮出现。
4. 进入 **资料库** 底部 **我的记忆**：新增 `session_summary`、`weakness`、`profile`。

### 2.4 跨会话验证（关键）

1. 刷新页面或开新会话，问：`再讲讲正则化，我上次哪里没搞懂？`
2. 预期：回答开头会提到你上次的卡点或偏好；注入记忆列表至少含 `profile` 与 `weakness`。
3. 轨迹里 `build_context` 的 payload 可以看到注入的 artifact ID 与 kind 计数。

### 2.5 今日复习与判分

1. 进入 **今日复习**。预期统计：待复习、未练习、平均掌握度·薄弱、今日已答·正确。
2. 点 **开始 5 题**。题目全部来自真实原文：一半是“原文出自哪个知识点”，一半是“哪段原文讲这个知识点”。
3. 故意答错 1–2 题并提交。预期每题结果：
   - 你的选择 / 正确答案 / 解释；
   - `掌握度 X% → Y%`；
   - 引用 chunk ID；
   - 答错显示“30 分钟后”再次复习。
4. 返回队列：刚答错的知识点应在 30 分钟后到期；答对的按 1 天/3 天/间隔 × ease 递进。
5. 刷新首页，导航“今日复习”角标与统计一致。

### 2.6 学习计划

1. 在 **今日复习** 点 **生成 3 天计划**。
2. 预期：计划卡列出 5 个知识点、当前待复习数、trace ID、memory artifact ID；标记“已写入 PowerContext · plan”。
3. 再点一次：标记变为“复用已有 PowerContext · plan”，artifact ID 不变。
4. 在 **资料库 → 我的记忆** 能看到对应 `plan` 记忆。

### 2.7 轨迹与布局

- 技术轨迹抽屉按 `seekdb / powercontext / app / llm` 分层；每行显示操作、条数、摘要，展开可见 payload。
- 窗口缩到 375 px 左右：三页仍可操作，导航折叠为图标，不出现横向滚动。

---

## 3. 接口逐项验证（curl）

以下命令在 Git Bash / macOS 终端可直接运行；PowerShell 请使用 `curl.exe` 并把单引号 JSON 改为双引号转义。

```bash
BASE=http://127.0.0.1:8090

# 健康
curl -s $BASE/health

# 导入
curl -s -X POST $BASE/api/ingest/seed \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"manual"}'

# 混合检索：每条结果必须有 chunk_id/doc_id/doc_title/section/page
curl -s -X POST $BASE/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"正则化和过拟合是什么关系","mode":"hybrid","top_k":3,"session_id":"manual"}'

# 问答：同时返回 citations、injected_memories、trace_ids
curl -s -X POST $BASE/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"正则化和过拟合是什么关系？","session_id":"manual-1","mode":"hybrid","top_k":5}'

# 收尾：写入 summary / weakness / profile
curl -s -X POST $BASE/api/session/close \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"manual-1","topic":"正则化与过拟合","struggles":"L1 和 L2 的区别总是记反","preference":"先给一句话结论，再配一个中文例子"}'

# 今日队列
curl -s "$BASE/api/review/today?limit=5"

# 出题 → 提交（question_id 换成上一步返回值）
curl -s -X POST $BASE/api/quiz/generate \
  -H 'Content-Type: application/json' \
  -d '{"limit":3,"session_id":"manual-quiz"}'

curl -s -X POST $BASE/api/quiz/submit \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"manual-quiz","answers":[{"question_id":"q-xxxxxxxxxxxxxxxx","chosen":"选项原文"}],"note":"概念记反"}'

# 计划（连续调用两次，第二次 reused=true 且 artifact_id 相同）
curl -s -X POST $BASE/api/review/plan \
  -H 'Content-Type: application/json' \
  -d '{"days":3,"limit":5,"session_id":"manual-plan"}'

# 轨迹与记忆
curl -s "$BASE/api/traces?limit=20"
curl -s "$BASE/api/memory?limit=20"
```

### 关键响应字段

| 接口 | 必须出现 |
| --- | --- |
| `/api/search` | `results[].chunk_id/doc_id/doc_title/section/page/score/relevance`、`trace_id` |
| `/api/ask` | `mode`（`llm` 或 `evidence`）、`answer`、`citations`、`injected_memories`、`trace_ids.seekdb/memory/answer` |
| `/api/session/close` | `summary`、`memories[]`、`trace_counts` |
| `/api/quiz/submit` | `results[].mastery_before/mastery_after/answer/explanation/source_chunk_id/next_review_at`、`memories[]` |
| `/api/review/plan` | `plan`、`queue[]`、`memories[]`、`reused`、`trace_id` |

---

## 4. 数据层原始证据

自动脚本：

```bash
.venv/Scripts/python.exe scripts/evidence.py    # Windows
# .venv/bin/python scripts/evidence.py          # macOS
```

它会直接读 seekdb 关系表，并通过 PowerContext HTTP API 列出原始条目。输出包含：

- `study_documents`：3 份文档及 chunk 数；
- `study_chunks`：chunk 总数（27）；
- 知识点 + 掌握度（score / interval / repetitions / lapses / next_review_at）；
- 今日练习记录（含 `is_correct`）；
- 最近 12 条轨迹与分层计数；
- PowerContext scope、kind 计数与 20 条原文。

### 手动 SQL（与脚本等价）

```bash
.venv/Scripts/python.exe - <<'PY'
from app.seekdb import db
import json
rows = db.query_all("""
  SELECT kp.name, m.score, m.interval_days, m.next_review_at
  FROM study_knowledge_points kp
  LEFT JOIN study_mastery m ON m.kp_id=kp.kp_id
  ORDER BY m.score ASC LIMIT 5
""")
print(json.dumps(rows, ensure_ascii=False, default=str, indent=2))
PY
```

### PowerContext 原始 HTTP

```bash
# 1) 取 scope_id
curl -s "http://127.0.0.1:8090/api/memory?limit=1"

# 2) 用 scope_id 列原始条目
curl -s -X POST http://127.0.0.1:8010/v1/memory/entries/list \
  -H 'Content-Type: application/json' \
  -d '{"scope_id":"<上一步的 scope_id>","limit":5}'
```

预期每条包含 `kind`、`text`、`artifact.artifact_id`、`state`。`kind` 分布应覆盖 `profile / weakness / session_summary / plan / task_state`（`task_state` 需要至少提交过一次练习）。

### 时区核对

`UTC_TIMESTAMP(6)` 与 Python 的 naive UTC 必须一致。若“今日已答”大于 0 但队列仍把刚练过的点算到期，先检查服务是否重启到了最新代码：

```bash
curl -s http://127.0.0.1:8090/health | grep version   # 应为 0.6.0 / S6
```

---

## 5. 截图清单

全部为 1440×1000 PNG，位于 `docs/screenshots/`。截图拍摄时的数据状态与“预期看到”一列一致；后续验收会改变数字，但界面结构不变。

| 文件 | 场景 | 预期看到 |
| --- | --- | --- |
| `01_ask_answer.png` | 问答页回答 | 问题、证据式回答、引用编号、右侧注入记忆入口 |
| `02_ask_injected_memories.png` | 注入记忆 | 本轮从 PowerContext 注入的 kind、正文、artifact ID |
| `03_trace_drawer.png` | 技术轨迹 | seekdb / powercontext / app 分层，chunk 相似度与记忆条目 |
| `04_review_before.png` | 复习前 | 待复习统计、SM-2 队列、未练习知识点 |
| `05_quiz_questions.png` | 出题 | 5 道由原文生成的题、选项、进度 |
| `06_quiz_result.png` | 判分总览 | 正确数 / 总数、每题对错 |
| `06_quiz_result_detail.png` | 判分明细 | 答错选项、正确答案、`40% → 32%`、引用 chunk、30 分钟后复习 |
| `07_review_after.png` | 复习后 | 20 待复习、20 未练习、48% 平均掌握度·薄弱 5、10 已答·正确 2 |
| `08_study_plan.png` | 学习计划 | 计划正文、5 个知识点、trace 与 memory artifact ID、“复用已有 PowerContext · plan”（重复点击时） |
| `09_library.png` | 资料库 | 3 文档 / 27 chunks / 3 学科 / 512 维、记忆统计 17 条 |
| `10_memories.png` | 我的记忆 | 统计卡（17 / 8 / 1 / 2）与五种 kind 的记忆卡片 |

> 截图与当前运行数据的条数可能不同；评审时以界面元素、字段与交互为准。

---

## 6. 验收失败时怎么定位

| 失败点 | 先看 |
| --- | --- |
| `/health` 的 PowerContext 不是 ready | PowerContext 是否在 8090 之后启动；`data/powercontext.log` 是否有 embedding timeout |
| `/api/ask` 503 | PowerContext 是否在 8010；`curl http://127.0.0.1:8010/health/ready` |
| 检索结果为空 | 是否已导入；`GET /api/documents`；学科过滤是否过窄 |
| 记忆注入为空 | 是否先做过会话收尾/练习；`/api/memory` 是否为空；scope 是否一致 |
| 掌握度不变 | 是否提交了 `question_id`；题目是否来自当前库（重建知识点后旧题 ID 可能失效） |
| 计划 400 | 队列为空（资料未导入或全部未到期）；先导入并刷新 |
| 时区错乱 | 服务版本是否 0.6.0；SQL 是否使用 `UTC_TIMESTAMP` / `UTC_DATE` |

---

## 7. 验收记录

| 日期 | 版本 | 结果 |
| --- | --- | --- |
| 2026-11-01 | 0.6.0 / S6 | `scripts/verify.py` 11 步全部 PASS；3 文档 / 27 chunks；跨会话注入 10 条；判分 0.5 → 0.4；计划复用同一 artifact；三层轨迹齐全 |
