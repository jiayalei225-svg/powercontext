# S7 · 干净环境复现记录

本文件记录一次**从空数据目录开始**的完整复现，用于证明结果不是靠已有运行状态“摆拍”出来的。

- 日期：2026-11-01
- 版本：`0.6.0` / `S6`
- 分支：`2026-competition-ecosystem`
- 环境：Windows 11 · Python 3.13 · 嵌入式 seekdb · PowerContext 1.4.1 · BGE-small-zh-v1.5（512 维）
- 原始日志：[verify-clean-run.txt](samples/verify-clean-run.txt) · [evidence-clean-run.txt](samples/evidence-clean-run.txt)

---

## 1. 复现步骤

1. 停止 StudyCoach 与 PowerContext。
2. 删除运行时目录（保留模型缓存）：
   ```bash
   rm -rf data/seekdb data/powercontext data/uploads
   ```
3. 先启动应用，等 `/health` 正常：
   ```bash
   python -m app.run
   curl http://127.0.0.1:8090/health
   ```
4. 再启动 PowerContext，等 `/health/ready` 为 `ready`：
   ```bash
   scripts\start_powercontext.bat     # macOS: ./scripts/start_powercontext.sh
   curl http://127.0.0.1:8010/health/ready
   ```
5. 运行自动验收：
   ```bash
   python scripts/verify.py
   ```
6. 导出原始证据：
   ```bash
   python scripts/evidence.py
   ```

> 顺序不能反：PowerContext 启动时会探测 `POST /v1/embeddings`，应用未监听时会把嵌入检查缓存为 timeout，记忆服务保持 degraded。

---

## 2. 空库基线

删除数据后、导入前，`GET /health` 的 seekdb 部分：

```json
{
  "status": "ok",
  "documents": 0,
  "chunks": 0,
  "knowledge_points": 0
}
```

PowerContext 启动后：

```json
{
  "status": "ready",
  "checks": {
    "runtime": "ready",
    "database": "ready",
    "inference.embedding": "ready"
  }
}
```

---

## 3. 自动验收结果

完整输出见 [samples/verify-clean-run.txt](samples/verify-clean-run.txt)。关键片段：

```
[2. 导入种子资料（幂等）]
  PASS  文档已入库 · 3 份 · 本次跳过 0
  PASS  chunk 已建索引 · 27 chunks

[3. 混合检索与引用契约]
  PASS  返回检索结果 · 5 条 · hybrid · keywords=['正则化', '过拟合', '关系']
  PASS  每条结果带引用字段 · chunk_id, doc_id, doc_title, section, page

[4. 第一轮问答（seekdb + PowerContext 同时调用）]
  PASS  回答模式明确 · evidence
  PASS  回答引用了 seekdb 结果 · 5 条引用
  PASS  有 seekdb trace
  PASS  有记忆 trace

[5. 会话收尾写回记忆]
  PASS  收尾写入记忆 · 本次新增 3 条 · ['profile', 'session_summary', 'weakness']
  PASS  收尾轨迹覆盖两层 · {'seekdb': 8, 'powercontext': 8, 'app': 2}

[6. 第二轮问答（跨会话记忆注入）]
  PASS  注入了跨会话记忆 · 3 条 · ['profile', 'session_summary', 'weakness']

[7. 记忆列表]
  PASS  记忆可列出 · 3 条 · ['profile', 'session_summary', 'weakness']

[8. 今日复习队列]
  PASS  队列非空 · 10 个 · due=27

[9. 出题、判分与掌握度]
  PASS  由原文生成题目 · 3 题 · {'queue': 3, 'new': 3, 'knowledge_points': 27}
  PASS  结果含掌握度与出处 · mastery 0.5 → 0.4
  PASS  练习进展写入 PowerContext · ['task_state', 'weakness']
  PASS  答错写入错因记忆 · 错 2 题
        wrong example: 「梯度下降」 next=30 分钟后
  PASS  今日已答计数增加 · answered_today=3

[10. 学习计划写入与复用]
  PASS  计划有正文 · 5 个知识点
  PASS  计划写入 PowerContext · art_3bf1fc614b9740989cca09d11edf5af7
  PASS  重复生成复用同一条 · art_3bf1... == art_3bf1...

[11. 技术轨迹分层]
  PASS  有 seekdb 轨迹
  PASS  有 PowerContext 轨迹
  PASS  有应用轨迹 · ['app', 'powercontext', 'seekdb']

ALL PASS · 问答、记忆、复习、计划与轨迹均已跑通
```

注意：干净环境下第二轮只注入了 3 条记忆（1 条摘要 + 1 条薄弱点 + 1 条偏好）。演示模式或多次练习后记忆变多，注入条数会增加，这是数据状态差异，不是逻辑差异。

---

## 4. 原始证据

完整输出见 [samples/evidence-clean-run.txt](samples/evidence-clean-run.txt)。以下是复现时的实际值。

### 4.1 seekdb 文档

| doc_id | 标题 | 学科 | chunks |
| --- | --- | --- | --- |
| `handwritten-notes` | 我的手写复习笔记（扫描整理） | 学习笔记 | 4 |
| `linear-algebra-lecture` | 线性代数核心讲义 | 线性代数 | 11 |
| `ml-lecture` | 机器学习基础讲义 | 机器学习 | 12 |

`study_chunks` 总数：**27**。

### 4.2 掌握度与调度

练习后部分行（来自 `study_mastery`）：

| 知识点 | score | interval_days | lapses | next_review_at |
| --- | --- | --- | --- | --- |
| 梯度下降 | 0.4 | 1 | 1 | 2026-11-01 04:32:46（30 分钟） |
| 正则化与过拟合 | 0.4 | 1 | 1 | 2026-11-01 04:32:46（30 分钟） |
| 特征值与 PCA | 0.625 | 1 | 0 | 2026-11-02 04:02:46（1 天） |

未练习的知识点没有 `study_mastery` 行，队列会标记为 `new`。

### 4.3 技术轨迹

| layer | 行数（本次复现） | 典型 operation |
| --- | --- | --- |
| seekdb | 16 | `ingest_document`、`search`、`quiz_generate`、`quiz_submit`、`review_today`、`build_plan` |
| powercontext | 20 | `search_memory`、`list_memory`、`remember:*`、`build_context` |
| app | 3 | `answer`、`session_close` |

### 4.4 PowerContext 原始条目

scope：`scp_7b56cc19ky7f66g5g5kc7agn0y`（每次干净初始化都会不同）。

kind 计数：

```json
{
  "session_summary": 1,
  "weakness": 4,
  "task_state": 1,
  "profile": 1,
  "plan": 1
}
```

`weakness` 的 4 条来自：2 道答错题 + 1 条错因备注 + 1 条会话自述卡点。摘要中的问题已去重，不再出现同一问题因标点不同而重复两次。

每条记忆都有真实 `artifact_id`，可在 `GET /api/memory`、技术轨迹与 UI 中互相对照。

---

## 5. 四项基本验收

| # | 要求 | 本次复现证据 |
| --- | --- | --- |
| 1 | seekdb 导入、切块、混合检索、引用字段 | 3 文档 / 27 chunks；hybrid 返回 5 条；每条含 `chunk_id/doc_id/doc_title/section/page` |
| 2 | PowerContext 跨会话记忆注入 | 第一轮收尾写入 3 条；第二轮注入 3 条（profile / weakness / summary）；原始条目可见 |
| 3 | 掌握度与 SM-2 | 判分 `0.5 → 0.4`；答错 30 分钟后；`lapses=1`；队列 due 从 27 起算 |
| 4 | 技术轨迹可追溯 | seekdb 16 行 / powercontext 20 行 / app 3 行；UI 抽屉与 `/api/traces` 一致 |

---

## 6. 五个评分风险与处理

### 风险 1：两个系统都调用了，但分工说不清

- **风险**：评审看到“两个都用了”，但无法判断各自不可替代的价值。
- **处理**：
  - 代码层按 `app/seekdb` 与 `app/memory` 分离，写入时机不同；
  - README 与网站文案用表格明确“知识归 seekdb、人归 PowerContext”；
  - 一次问答的 trace 同时包含 `seekdb/search` 与 `powercontext/build_context`，可逐条核对；
  - 验收脚本第 4、6 步分别断言 seekdb 引用与记忆注入。
- **剩余风险**：低。两个系统的调用不是装饰性的，任一侧失败都会显式报错或降级留痕。

### 风险 2：记忆是“只写不读”或伪造的

- **风险**：只往 PowerContext 写，回答里却假装“记得你”。
- **处理**：
  - 第二轮问答实际调用 `search_memory` 与 `build_context`，注入的 artifact ID 与列表接口一致；
  - 回答由注入记忆驱动（evidence 模式会先说“我记住的情况”）；
  - `scripts/verify.py` 第 6 步断言注入条数 > 0，并打印首条记忆；
  - 原始证据列出 scope 内全部条目。
- **剩余风险**：低。semantic recall 在词汇完全不重叠时可能漏召回，因此额外补读近期 profile/plan/task_state。

### 风险 3：检索结果不可追溯

- **风险**：只返回一段文本，无法证明来自哪份资料、哪一页。
- **处理**：
  - chunk 元数据契约固定为 `doc_id/doc_title/subject/section/page/chunk_id`；
  - 引用卡片与技术轨迹保留相似度、RRF 分与 chunk ID；
  - 题目解释回链 `source_chunk_id`；
  - 验收第 3 步逐字段断言。
- **剩余风险**：低。PDF 仅文本层，扫描件需 OCR（已在文档标注）。

### 风险 4：题目与答案是手写/硬编码的

- **风险**：题库看起来丰富，实际与资料无关。
- **处理**：
  - 两种题型都由真实 chunk 生成；
  - 干扰项来自其他知识点，选项按 `question_id` 确定性打乱；
  - 判分在服务端，结果返回原文出处；
  - 代码里没有手写题目表；导入新资料后题目随之变化。
- **剩余风险**：低。资料过少时可能生成不足 5 题，系统会少出而不是编造。

### 风险 5：一键启动、时区与交付文档拖后腿

- **风险**：评审克隆后起不来，或“刚练过仍显示到期”。
- **处理**：
  - 两个一键脚本固定 app → PowerContext 顺序，并等待健康检查；
  - SQL 统一 `UTC_TIMESTAMP(6)` / `UTC_DATE()`；
  - `.env.example` 全占位、`.env` 被忽略；
  - 提供 `scripts/verify.py`、`scripts/evidence.py` 与三份文档；
  - 本次干净复现即为验证。
- **剩余风险**：中低。Docker 路径未在本机验证，已在 README 与文案中明确标注；真实 LLM key 未在本机配置，evidence 模式已完整验证。

---

## 7. 已知未验证项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| Docker 部署 | 未验证 | 本机无 Docker；编排文件已提供，README 明确标注，不作为主路径 |
| 真实 LLM 端点 | 未验证 | `LLM_BASE_URL` 为空，evidence 模式完整可用；LLM 调用失败会写 trace 并回退 |
| PDF OCR | 未实现 | 仅文本层提取，扫描件会提示无文本 |
| 多用户隔离 | 未实现 | 单用户 `USER_ID=local` + 单一项目 scope |
| macOS 实机 | 未实测 | 启动脚本按 bash 编写，逻辑与 Windows 版本对应；本机未在 macOS 运行 |

---

## 8. 截图说明

`docs/screenshots/` 的截图来自一次更长的演示会话（多轮问答、5 题练习、计划生成），因此记忆条数（17）与今日已答数（10）高于本次干净复现（8 条记忆、3 道练习）。两张证据图与截图不要求数字一致；以界面字段、交互与日志为准。

本次干净复现未重新截图，因为界面结构未变化，且截图的目的是展示功能而不是绑定某次数据。
