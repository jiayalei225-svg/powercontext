# StudyCoach · 个人学习与复习教练

把散落在讲义、笔记和论文里的知识点，变成**找得到、记得住、会安排**的学习工作台。

> 每一个回答都先查 seekdb 里的教材原文，再读 PowerContext 里关于你的长期记忆：引用可追溯，建议会提到你上次卡在哪。

---

## 目录

- [为什么做这个](#为什么做这个)
- [已经能做什么](#已经能做什么)
- [两个系统怎么分工](#两个系统怎么分工)
- [一次问答的真实调用链](#一次问答的真实调用链)
- [快速开始](#快速开始)
- [5 分钟验收](#5-分钟验收)
- [页面与接口](#页面与接口)
- [seekdb 设计](#seekdb-设计)
- [PowerContext 设计](#powercontext-设计)
- [掌握度与复习调度](#掌握度与复习调度)
- [技术轨迹](#技术轨迹)
- [配置项](#配置项)
- [数据与重置](#数据与重置)
- [Docker 备选部署](#docker-备选部署未验证)
- [故障排查](#故障排查)
- [已知边界](#已知边界)
- [目录结构](#目录结构)
- [相关文档](#相关文档)

---

## 为什么做这个

三个问题同时存在，学习资料才真正“用不起来”：

1. **资料散**：讲义、笔记、论文各在一处，找一个概念只能 Ctrl+F，换个说法就搜不到。
2. **复习没计划**：熟悉的章节反复看，薄弱的章节下意识躲开；没有“今天该复习什么”的队列。
3. **助手没有记性**：每次开新会话都要重新交代“我在学什么、哪里不懂、希望怎么讲”。

StudyCoach 把三件事接成一条闭环：**入库 → 混合检索 → 带记忆回答 → 出题 → 掌握度/调度 → 会话收尾写回记忆**。

## 已经能做什么

S1–S6 功能已完成，S7 干净环境复现已通过。所有页面均可交互：

| 能力 | 实现 |
| --- | --- |
| 资料入库 | md / txt / pdf 上传或一键导入示例；按章节切块，写入 seekdb 并建全文/向量索引 |
| 混合检索 | 向量 + 全文 + 元数据过滤，加权 RRF 融合；权重可配置；每条结果带 `doc_id / doc_title / section / page / chunk_id` |
| 带记忆问答 | 每次问答同时查 seekdb 与 PowerContext；注入最多 8 条相关记忆 + 稳定的偏好/计划/任务进展 |
| 会话收尾 | 提取本轮知识点、错因、新偏好，写回 PowerContext 的五种 memory |
| 今日复习 | 到期队列、未练习优先、薄弱优先；首页导航显示“今日 N”角标 |
| 出题与判分 | 题目全部由 seekdb 原文生成（原文找知识点 / 知识点找原文），服务端判分 |
| 掌握度与 SM-2 | 答对加分、答错扣分、时间衰减；下次复习 1 天 → 3 天 → 间隔 × ease；答错 30 分钟后重来 |
| 学习计划 | 按实时复习队列生成 3 天计划并写入 PowerContext；重复点击复用同一条计划 |
| 技术轨迹 | seekdb / PowerContext / 应用 / LLM 四层轨迹，抽屉里可核对 chunk 相似度与注入的记忆 |
| 本地嵌入 | 本地 BGE-small-zh-v1.5 ONNX（512 维），seekdb 与 PowerContext 共用同一个向量空间，无需外部 key |

## 两个系统怎么分工

不是“两个都调一下”，而是各管一件事：

| | **seekdb** | **PowerContext** |
| --- | --- | --- |
| 管什么 | **知识**：教材原文、章节、页码、向量与全文索引 | **你**：偏好、薄弱点、会话摘要、计划、任务进展 |
| 写什么 | `study_chunks` collection；文档/知识点/题库/练习/掌握度/会话/轨迹等 9 张关系表 | 5 种 memory：`profile`、`weakness`、`session_summary`、`plan`、`task_state` |
| 怎么读 | 向量 + 全文 + 元数据过滤，加权 RRF；结果可定位到 chunk | 语义召回 + 稳定的偏好/计划补读；按 kind 在应用层过滤 |
| 为什么不能互换 | 原文需要精确引用与页码，必须可追溯到 chunk | 用户状态是自然语言、会演化，需要跨会话语义召回 |
| 谁写 | 导入、答题判分、SM-2 更新、复习队列 | 会话收尾、练习提交、计划生成、手动写入 |

**硬规则**：`POST /api/ask` 一定先做 seekdb 检索，再做 PowerContext 召回；两者任一失败都会在响应/轨迹里显式报错，不会用编造内容兜底。

## 一次问答的真实调用链

```
问题
 │
 ├─ 1. seekdb 混合检索（app/retrieval/hybrid.py）
 │     ├─ 向量分支：BGE 嵌入 → 相似 chunk
 │     ├─ 全文分支：jieba 关键词 → $contains 字面匹配
 │     ├─ 元数据过滤：subject / doc_id / section
 │     └─ RRF 融合：0.6/(60+vector_rank) + 0.4/(60+fts_rank)
 │     → trace: layer=seekdb, operation=search
 │
 ├─ 2. PowerContext 记忆召回（app/memory/service.py）
 │     ├─ 语义召回 top 8（hybrid，失败时 fts 降级并记录）
 │     ├─ 补读近期 profile / plan / task_state，去重后最多 10 条
 │     └─ 渲染 <<<MEMORY_CONTEXT>>> 块
 │     → trace: layer=powercontext, operation=search_memory / build_context
 │
 ├─ 3. 回答（app/coach/answer.py）
 │     ├─ 配置了 LLM：OpenAI 兼容 /chat/completions，证据 + 记忆一起进 prompt
 │     └─ 未配置：evidence 模式，直接用检索原文 + 记忆拼装，不编造
 │     → trace: layer=app, operation=answer（含引用、记忆 ID、耗时）
 │
 └─ 4. 前端展示
       答案 + 引用卡片 + 注入记忆 + 技术轨迹抽屉
```

## 快速开始

### 前置条件

- Python **3.11+**（本项目在 Python 3.13 / Windows 11 上验证）
- 首次运行需要网络：安装依赖、下载 BGE ONNX 模型（约 100 MB）
- 端口：StudyCoach **8090**，PowerContext **8010**；被占用时改 `.env`

### Windows 一键启动

```
双击 qoder\start_windows.bat
```

脚本会：创建/复用 `.venv` → 安装 `requirements.txt` → 从 `.env.example` 生成 `.env` → **先启动 8090 应用** → 等 `/health` 通过 → 启动 8010 PowerContext → 等 `/health/ready` 变为 `ready` → 打开浏览器。

### macOS 一键启动

```bash
cd qoder
chmod +x start_macos.sh
./start_macos.sh
```

按 `Ctrl+C` 会同时停止脚本启动的两个进程。日志在 `data/app.log` 与 `data/powercontext.log`。

### 手动启动（两个终端）

```bash
# 终端 1：应用（必须先起）
cd qoder
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # 仅首次
python -m app.run

# 终端 2：PowerContext（等 8090 的 /health 正常后再起）
cd qoder
source .venv/bin/activate
./scripts/start_powercontext.sh  # Windows: scripts\start_powercontext.bat
```

**为什么必须 app 先起？** PowerContext 启动时会探测 `POST /v1/embeddings` 并缓存结果；如果先起 PowerContext，嵌入检查会停在 `timeout`，记忆服务显示 `degraded`（写入仍可用，但语义召回质量下降）。两个一键脚本都已按正确顺序处理。

### 健康检查

```bash
curl http://127.0.0.1:8090/health
curl http://127.0.0.1:8010/health/ready
```

`/health` 应返回 `seekdb.status=ok`、`powercontext.ready=true`、`integrations.embedding.mode=local`。

## 5 分钟验收

1. 打开 `http://127.0.0.1:8090`，右上角显示 `seekdb · N chunks · 记忆已连接`。
2. 进入 **资料库** → 点 **导入示例资料**，得到 3 份文档 / 27 个 chunk / 3 个学科。
3. 进入 **问答** → 点 **演示模式**：自动导入种子资料、连续跑 3 轮问答并在每轮结束后写记忆；第 3 轮回答会带上第 1–2 轮的偏好与薄弱点。打开右侧 **技术轨迹** 可核对 seekdb 检索与 PowerContext 读写。
4. 进入 **今日复习** → **开始 5 题**：题目来自 seekdb 原文；提交后看每题的掌握度变化、正确答案、引用 chunk 与下次复习时间。
5. 同一页点 **生成 3 天计划**：计划写入 PowerContext（重复点击会复用同一条并标注），轨迹里能看到 `build_plan`。
6. 回到 **资料库** 底部查看 **我的记忆**：`profile / weakness / session_summary / plan / task_state` 均可展开核对。

更细的逐步验收、API 命令与截图清单见 [docs/verification.md](docs/verification.md)。

## 页面与接口

### 页面

- **今日复习**：统计卡（待复习 / 未练习 / 平均掌握度·薄弱 / 今日已答·正确）、SM-2 队列、开始 5 题 / 20 题模拟、生成 3 天计划。
- **问答**：混合/向量/全文模式切换、学科过滤、答案、引用卡片、注入记忆；结束本轮可填写卡点与偏好，写入记忆。
- **资料库**：文档列表、导入示例、上传并索引、删除；底部是 PowerContext 记忆列表与统计。
- **技术轨迹抽屉**：按 seekdb / powercontext / app / llm 分层展示，可看到 chunk 相似度、RRF 分数、注入记忆的 kind 与内容。

### HTTP 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 应用、seekdb、PowerContext、嵌入、LLM 状态 |
| POST | `/v1/embeddings` | OpenAI 兼容嵌入接口，供 PowerContext 调用 |
| POST | `/api/search` | 混合/向量/全文检索，支持 `subject/doc_id/section` |
| GET | `/api/documents` | 文档列表与统计 |
| POST | `/api/ingest/seed` | 导入 `data/seed/` |
| POST | `/api/ingest/upload` | 上传 md/txt/pdf 并索引 |
| DELETE | `/api/documents/{doc_id}` | 删除文档并重建知识点 |
| GET | `/api/traces` | 技术轨迹（可按 session 过滤） |
| GET | `/api/stats` | 文档/chunk/学科/嵌入统计 |
| POST | `/api/ask` | 检索 + 记忆注入 + 回答 |
| POST | `/api/session/close` | 会话收尾，写入记忆 |
| GET | `/api/memory` | 列出记忆 |
| GET | `/api/memory/status` | 记忆服务状态与计数 |
| POST | `/api/memory` | 手动写入一条记忆 |
| GET | `/api/session/{session_id}` | 会话与证据 |
| GET | `/api/review/today` | 今日队列与统计 |
| GET | `/api/knowledge` | 知识点列表 |
| POST | `/api/quiz/generate` | 由原文生成题目 |
| POST | `/api/quiz/submit` | 服务端判分并更新掌握度 |
| POST | `/api/review/plan` | 生成/复用学习计划并写入 PowerContext |

完整字段可在 `http://127.0.0.1:8090/docs` 查看。

## seekdb 设计

嵌入式模式：`pylibseekdb.open(SEEKDB_PATH)` 启动实例，`pyseekdb.Client` 与 `pymysql` 共用同一个数据目录，**不需要单独数据库服务**。

### 一个 collection：`study_chunks`

每个 chunk 的元数据契约固定为：

```
chunk_id, doc_id, doc_title, subject, section, page, chunk_index, source_path, imported_at
```

检索结果与引用卡片都直接读这些字段，所以“这句答案从哪一页来”不靠推测。

### 九张关系表

`study_documents`、`study_knowledge_points`、`study_kp_chunks`、`study_questions`、`study_practice_records`、`study_mastery`、`study_sessions`、`study_users`、`study_traces`。

- `study_knowledge_points` 由文档章节派生，`study_kp_chunks` 维护知识点与 chunk 的多对多关系。
- 掌握度、复习时间、练习记录都在关系表里，排序和聚合用 SQL，向量只负责语义召回。
- 时间统一存 **UTC**：Python 写 naive UTC，SQL 用 `UTC_TIMESTAMP(6)` / `UTC_DATE()`，避免本地时区导致“刚练过仍显示到期”。

### 混合检索

```
score(chunk) = 0.6 / (60 + vector_rank) + 0.4 / (60 + fts_rank)
```

- 权重来自 `HYBRID_VECTOR_WEIGHT` / `HYBRID_FTS_WEIGHT`，改环境变量即可复现不同融合。
- 全文分支先用 jieba 抽关键词（带领域词典），再逐词 `$contains`，合并去重。
- 向量分支距离会归一化为 `relevance`，融合分与单路分都保留在结果里，技术轨迹可核对。

## PowerContext 设计

- **独立实例**：本项目在 8010 启动自己的 PowerContext，数据在 `data/powercontext/`，不依赖机器上已有的 8000 实例。
- **项目 scope**：首次使用时按标题 `StudyCoach · {USER_ID}` 查找或创建，scope ID 缓存；并发创建用幂等键兜底。
- **五种 kind**：`profile`（偏好）、`weakness`（薄弱点/错因）、`session_summary`（会话摘要）、`plan`（计划）、`task_state`（任务进展）。PowerContext search 没有 kind 参数，因此应用层召回后按 kind 过滤。
- **注入策略**：先按问题语义召回最多 8 条，再补读近期 `profile/plan/task_state`，去重后最多 10 条，按 kind 稳定排序后放进提示词。语义召回可能漏掉“与问题用词无关”的偏好，补读就是为此。
- **写回时机**：
  - 会话收尾：摘要 + 用户自述卡点 + 规则识别/手填偏好；
  - 练习提交：当天任务进展 + 最多 3 条错题归因 + 错因备注；
  - 生成计划：整段计划文本；相同文本直接复用，避免重复记忆；
  - 手动写入：`POST /api/memory`。
- **降级可见**：PowerContext 不可用时 `/api/ask` 返回 503 并说明启动方法；记忆召回 hybrid 失败会降级到 fts，并在 trace 中记录 `fts_fallback`。

## 掌握度与复习调度

`app/scheduler/mastery.py` 是唯一计算处：

- 初始分 `0.5`，范围 `0.05–0.99`。
- 答对：`score += α × (1 − score)`，`α = 0.25`；ease `+0.1`（上限 3.0）。
- 答错：`score *= (1 − β)`，`β = 0.20`；ease `−0.2`（下限 1.3）；`lapses + 1`。
- 时间衰减：`score *= 0.85 ^ (未练习天数 / 14)`。
- 间隔：第 1 次 1 天，第 2 次 3 天，之后 `round(间隔 × ease)`，上限 180 天。
- 答错后 `next_review_at = now + 30 分钟`，当天重新进队列。
- 今日队列排序：未练习优先 → 掌握度低优先 → 到期时间早优先。

参数全部在 `.env`：`MASTERY_ALPHA`、`MASTERY_BETA`、`DECAY_DAYS`、`DECAY_FACTOR`。

## 技术轨迹

每次 seekdb 检索、PowerContext 读写、应用编排、LLM 调用都会写一行 `study_traces`：

```
trace_id, session_id, ts, layer, operation, input_text, result_count, summary, payload(JSON)
```

- `layer=seekdb`：`search`、`ingest_document`、`quiz_generate`、`quiz_submit`、`review_today`、`build_plan`
- `layer=powercontext`：`search_memory`、`list_memory`、`remember:{kind}`、`build_context`
- `layer=app`：`answer`、`session_close`
- `layer=llm`：`chat`（配置了 LLM 时）

前端抽屉按层展示；`payload` 里保留 chunk ID、相似度、RRF 分、注入记忆 ID 与 kind，用于赛后复核。

## 配置项

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8090` | 应用监听 |
| `APP_STAGE` | `S6` | 当前阶段标记，仅用于状态展示 |
| `USER_ID` | `local` | 本地单用户 ID，也是 PowerContext scope 的一部分 |
| `DATA_DIR` | `./data` | 运行时数据根目录 |
| `SEEKDB_PATH` | `./data/seekdb` | 嵌入式 seekdb 数据目录 |
| `MODEL_DIR` | `./data/models` | BGE ONNX 缓存根目录，实际文件在 `./data/models/bge-small-zh-v1.5/onnx/` |
| `POWERCONTEXT_URL` | `http://127.0.0.1:8010` | 本项目专用 PowerContext |
| `POWERCONTEXT_HOME` | `./data/powercontext` | PowerContext 数据目录（启动脚本读取） |
| `POWERCONTEXT_SCOPE_ID` | 空 | 留空则自动查找/创建 scope |
| `POWERCONTEXT_EMBEDDING_BASE_URL` | `http://127.0.0.1:8090/v1` | PowerContext 调用的嵌入端点 |
| `EMBEDDING_MODE` | `local` | `local`（BGE ONNX）或 `api` |
| `EMBEDDING_MODEL` | `bge-small-zh-v1.5` | 嵌入模型名 |
| `EMBEDDING_DIM` | `512` | 向量维度 |
| `HYBRID_VECTOR_WEIGHT` | `0.6` | 向量分支 RRF 权重 |
| `HYBRID_FTS_WEIGHT` | `0.4` | 全文分支 RRF 权重 |
| `HYBRID_TOP_K` | `10` | 默认返回条数 |
| `MASTERY_ALPHA` / `MASTERY_BETA` | `0.25` / `0.20` | 答对加分 / 答错扣分 |
| `DECAY_DAYS` / `DECAY_FACTOR` | `14` / `0.85` | 时间衰减 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 空 | 留空使用 evidence 模式 |

`.env.example` 只有占位值；真实 `.env` 已被 git 忽略，**不要把任何 key 写进仓库**。

## 数据与重置

运行时数据（均被 git 忽略）：

```
data/seekdb/       嵌入式数据库
data/powercontext/ PowerContext 数据
data/models/       BGE ONNX 缓存（bge-small-zh-v1.5/onnx/ 下约 90 MB）
data/uploads/      上传文件
```

重置到干净状态（先停服务）：

```bash
# macOS / Linux
rm -rf data/seekdb data/powercontext data/uploads

# Windows
rmdir /s /q data\seekdb data\powercontext data\uploads
```

保留 `data/models/` 可免去重新下载模型。重启后重新点“导入示例资料”即可。

## Docker 备选部署（未验证）

主路径是**嵌入式 seekdb + 一键脚本**，克隆即可运行。仓库另外提供 `docker/` 下的容器编排，作为隔离环境的备选：

```bash
cd qoder
docker compose -f docker/docker-compose.yml up --build
# 打开 http://127.0.0.1:8090
```

- `app` 容器运行 StudyCoach（8090），`powercontext` 容器运行记忆层（8010，仅容器内访问）。
- 两个容器共享 `studycoach-data` 卷：seekdb、PowerContext 数据与模型缓存都落在 `/data`。
- `powercontext` 通过 `depends_on: service_healthy` 等应用就绪后再启动，避免启动顺序导致的嵌入 `timeout`。

> **诚实说明**：作者本机（Windows 11）没有安装 Docker，以上编排**未做端到端验证**，请在具备 Docker 的环境自行冒烟。若容器路径遇到问题，以 `start_windows.bat` / `start_macos.sh` 的嵌入式路径为准；本 README 不声称 Docker 已验证。

## 故障排查

| 现象 | 原因 / 处理 |
| --- | --- |
| 8090 启动报 `WinError 10048` | 端口被占用。改 `.env` 的 `APP_PORT`，或结束占用进程；不要直接杀未知进程 |
| 记忆显示 `degraded`，`inference.embedding=timeout` | PowerContext 早于应用启动。关闭 PowerContext 窗口，确认 `/health` 正常后重启它 |
| `/api/ask` 返回 503 | PowerContext 未启动或地址不对。运行 `scripts/start_powercontext.*`，确认 8010 可访问 |
| 首次导入很慢 | 正在下载 BGE ONNX（约 100 MB）。可设 `HF_ENDPOINT=https://hf-mirror.com` |
| 导入后“今日复习”仍显示旧数据 | 重启应用刷新嵌入式连接；确认 SQL 使用 UTC 时间（本仓库已统一） |
| PDF 导入为空 | 目前只做文本层提取，扫描件/图片 PDF 需要 OCR，尚未支持 |
| 页面提示“记忆已断开” | 应用正常但 PowerContext 未 ready；按上一条处理，不影响资料检索 |

## 已知边界

- **LLM 可选**：未配置 key 时使用 evidence 模式，答案完全由检索原文 + 记忆拼装；配置任意 OpenAI 兼容端点即可切换为 LLM 生成，失败会回退并写 `layer=llm` 轨迹。
- **规则式收尾**：无 LLM 时，偏好识别用显式规则，卡点来自用户输入，不做“假装推断”。
- **单用户本地**：`USER_ID=local`，PowerContext 使用单一项目 scope；多用户隔离不在本次范围。
- **PDF**：仅文本层，无 OCR。
- **Docker**：见上节，未在本机验证。

## 目录结构

```
qoder/
  app/
    api/          HTTP 路由（health / embeddings / study / coach / review）
    ingest/       加载、切块、知识点派生
    retrieval/    向量 + 全文 + 过滤，加权 RRF
    memory/       PowerContext 客户端、kind、策略与 trace
    scheduler/    掌握度、SM-2、出题、今日队列、计划
    seekdb/       嵌入式连接、schema、关系表仓储
    trace/        轨迹契约
    web/          原生 HTML/CSS/JS（无构建链）
  data/seed/      三份可导入的示例资料（跟踪）
  docker/         可选容器编排（未验证）
  docs/           开发记录、验收、网站文案、截图
  scripts/        PowerContext 启动、验收脚本
  start_windows.bat
  start_macos.sh
  requirements.txt
  .env.example
```

## 相关文档

- [docs/verification.md](docs/verification.md)：验收步骤、API 命令、截图清单
- [docs/reproduction-log.md](docs/reproduction-log.md)：S7 干净环境复现记录与原始证据
- [docs/qoder-dev-log.md](docs/qoder-dev-log.md)：S1–S7 开发过程与踩坑
- [docs/website-content.md](docs/website-content.md)：参赛网站文案与截图说明
- [docs/self-check.md](docs/self-check.md)：提交前自检清单
