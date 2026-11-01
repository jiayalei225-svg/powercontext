# Qoder 开发记录

本文件按阶段记录实际开发过程，包括走过的弯路。提交信息与 git 历史对应。

## S1 · 方案定稿与骨架（2026-11-01）

### 目标

在 `qoder/` 下建立可运行的分层骨架：目录、seekdb 数据模型、PowerContext memory kind 体系、最小 FastAPI 服务、首页、环境变量与双平台启动脚本。

### 实际做了什么

- 从 `submission/2026-competition-ecosystem` 分支稀疏克隆仓库，只 checkout `qoder/`。
- 发现 `qoder/` 已有上一版 PaperDesk 项目（commit `43eea5ba`）。没有直接覆盖，先向用户确认；确认后使用 `git mv` 归档到 `qoder/archive/paperdesk/`，保留完整历史。
- 建立分层目录：`app/api`、`app/ingest`、`app/retrieval`、`app/memory`、`app/scheduler`、`app/seekdb`、`app/trace`、`app/web`。
- 在 `app/seekdb/schema.py` 定义 `study_chunks` collection 的元数据契约和 9 张关系表 DDL：文档、知识点、知识点-chunk 关联、题库、练习记录、掌握度、会话、用户、技术轨迹。
- 在 `app/memory/kinds.py` 定义 `profile / weakness / session_summary / plan / task_state` 五种 kind，以及带 `[kind=...][subject=...][topic=...][at=...]` 首行的文本信封。
- 实现最小 FastAPI：`GET /health` 与首页 `/`，静态资源挂在 `/static`。
- 首页使用原生 HTML/CSS/JS，无构建链；显示后端状态、三个模块占位与技术分工。
- 提供 `.env.example`、`requirements.txt`（固定版本）、`start_windows.bat`、`start_macos.sh`、PowerContext 启动脚本。
- 编写 S1 版 README，说明启动、验证、目录与数据模型。

### 遇到的问题与处理

1. `qoder/` 不是空目录，已有 PaperDesk。处理：不覆盖，询问后 `git mv` 到 `qoder/archive/paperdesk/`。
2. 本机 8080 已被旧的 PaperDesk 进程占用，首次 `uvicorn` 启动报 `WinError 10048`。处理：不杀用户进程，把默认端口改为 8090，并同步修改配置、脚本与 README。
3. Windows 没有 Docker，而赛题允许嵌入式 seekdb。处理：确认 `pylibseekdb 1.4.0.post2` 有 `cp312-abi3-win_amd64` 轮子，Python 3.13 可用；Docker 只作为 S6 的备选说明。
4. PowerContext 的 `memory/search` 没有 kind 过滤参数。处理：在 S1 就把 kind 写进记忆文本首行，S3 按 kind 在应用层过滤，避免后续返工。

### 验证结果

- `start_windows.bat` 成功创建/复用 `.venv`、安装依赖、生成 `.env`，服务监听 `http://127.0.0.1:8090`。
- `GET /health` 返回 `status=ok`、`stage=S1`。
- 浏览器打开首页，状态显示“后端正常 · 0.1.0 · S1”，无控制台错误；3 张模块卡片、2 个技术分工面板均渲染。
- 在临时嵌入式 seekdb 上执行全部 DDL，9 张表创建成功，`study_mastery` 插入与排序查询正常。
- `build_memory_text` / `parse_memory_text` 往返测试通过，kind、subject、topic、正文均正确。

### 对应提交

`feat(qoder): S1 skeleton with layered layout, seekdb schema and memory kinds`

---

## S2 · 嵌入式 seekdb、切块与混合检索（2026-11-01）

### 目标

让“资料散”这一条真正可解：文件可导入、按章节切块、写入 seekdb，问答时能用向量 + 全文 + 元数据过滤找回原文，并且每条结果可定位。

### 实际做了什么

- `app/ingest/loaders.py`：md / txt / pdf 加载；PDF 用 pypdf 逐页提取文本，页码进入元数据。
- `app/ingest/chunker.py`：Markdown 按标题层级切块，普通文本按段落/长度切块，保留 `section` 与 `page`。
- `app/seekdb/db.py`：同一数据目录开两个句柄——`pyseekdb.Client` 管 `study_chunks` collection，`pylibseekdb` + `pymysql` 管关系表。选择 pymysql 是因为底层 cursor 只接受字符串拼接，无法安全做参数绑定。
- `app/seekdb/schema.py`：collection 元数据契约 + 9 张关系表 DDL，应用启动时幂等建表。
- `app/ingest/pipeline.py`：内容哈希去重；同一文档重新导入先删旧 chunk；每次导入写 `seekdb/ingest_document` 轨迹。
- `app/retrieval/hybrid.py`：向量、全文、混合三种模式；全文分支用 `hybrid_search(knn=None)` 做 `$contains`；融合用加权 RRF（0.6 / 0.4，k=60）。
- 前端加“资料库”与检索结果卡片，显示标题、学科、章节、页码、相似度与引用片段。

### 遇到的问题与处理

1. **中文全文检索被分词带偏**：jieba 把“正则化”切成“正则 / 化上”，字面分支搜不到原文。处理：加领域词典（正则化、过拟合、特征值等）与停用词/函数字过滤，关键词优先取更长词组。
2. **两种句柄写同一目录**：collection 与关系表必须看到同一份数据，不能用两个路径。处理：`SEEKDB_PATH` 单一来源，两个句柄都指向它。
3. **向量距离与融合分含义不同**：直接混排会让“距离小”和“排名高”互相打架。处理：向量分支只保留排名，融合后再把最终分归一化为 `relevance`；原始分与 RRF 分都留在 trace。
4. **重复导入**：反复点“导入示例资料”会重复写 chunk。处理：`content_hash` 未变直接跳过，并在 trace 里标注 `skipped`。

### 验证结果

- 3 份种子资料导入为 27 个 chunk、27 个知识点，重复导入全部跳过。
- 同一问题在 `hybrid / vector / fulltext` 三种模式下均返回结果，且每条都含 `doc_id / doc_title / section / page / chunk_id`。
- 导入与检索均能在 `/api/traces` 看到 `layer=seekdb` 的记录。

### 对应提交

`feat(qoder): S2 embedded seekdb ingestion, hybrid retrieval and search UI`（`8167a80a`）

---

## S3 · PowerContext 记忆闭环（2026-11-01）

### 目标

解决“助手没有记性”：把偏好、薄弱点、会话摘要、计划、任务进展写进 PowerContext，并在下一次问答时注入提示词。

### 实际做了什么

- 用 `powercontext[server,cli]==1.4.1` 在 **8010** 起项目专用实例，数据落 `data/powercontext/`，不碰本机 8000 上的其他实例。
- `app/memory/client.py`：薄 HTTP 客户端，覆盖 scope / remember / search / list / readiness。
- `app/memory/service.py`：scope 查找或创建（幂等键兜底并发）、五种 kind、应用层 kind 过滤、hybrid 失败降级 fts、每次读写写 `layer=powercontext` 轨迹。
- `app/memory/kinds.py`：`profile / weakness / session_summary / plan / task_state`。
- `app/coach/session.py`：会话收尾。无 LLM 时用规则识别偏好（“一句话”“先结论”“举例”等），卡点来自用户输入，摘要来自本轮实际检索到的章节与问题。
- `app/coach/answer.py`：配置 LLM 时走 OpenAI 兼容接口；未配置时用 evidence 模式拼装原文与记忆；两种模式都标注 `mode`。
- `app/api/embeddings.py`：把本地 BGE 暴露成 `/v1/embeddings`，PowerContext 启动时指向它，两个系统共用同一向量空间。
- 问答页增加“本轮注入的记忆”、会话收尾表单与技术轨迹入口。

### 遇到的问题与处理

1. **PowerContext 需要嵌入服务**：它自己不能跑 ONNX，没有 key 时记忆索引不可用。处理：由 StudyCoach 提供 OpenAI 兼容嵌入端点，PowerContext 配置为 `openai:bge-small-zh-v1.5`。
2. **search 没有 kind 过滤参数**：无法只召回 weakness。处理：按 `top_k × 3` 召回后在应用层过滤，再用稳定 kind 顺序排序；这比给 PowerContext 打补丁更可控。
3. **语义召回可能漏掉偏好**：问题与“希望先给结论”没有词汇重叠。处理：`build_memory_context` 在语义召回后再补读近期 `profile / plan / task_state`，去重后最多 10 条。
4. **写入必须可核对**：每次 remember/search/list 都写 trace，失败也写，payload 带 artifact ID 与 kind，前端可直接展示。
5. **启动顺序**：PowerContext 启动时会探测嵌入端点。最初先起它，检查结果缓存为 `timeout`，记忆一直 `degraded`。处理：一键脚本改为应用先起、健康检查通过后再起 PowerContext（详见 S6）。

### 验证结果

- 会话 A 提问并收尾，写入 summary + weakness + profile；会话 B 用新 session 再问，注入记忆中能看到 A 的偏好与卡点，回答开头会提到“上次卡在哪”。
- `/api/memory/status` 返回 5 种 kind 的计数；技术轨迹里 `search_memory`、`build_context`、`remember:*` 均可见。
- PowerContext 停掉时 `/api/ask` 明确返回 503，不会生成假回答。

### 对应提交

`feat(qoder): S3 PowerContext memory loop with injectable context and close-out`（`825303d3`）

---

## S4 · 知识点、掌握度与 SM-2 复习（2026-11-01）

### 目标

把“复习没计划”做成可计算、可验证的队列：知识点、题目、判分、掌握度、下次复习时间全部来自 seekdb 数据。

### 实际做了什么

- `app/ingest/knowledge.py`：从文档章节派生知识点，维护 `study_kp_chunks` 多对多关系；资料增删后重建。
- `app/scheduler/quiz.py`：两种题型都由真实 chunk 生成——`excerpt_to_kp`（原文找知识点）与 `kp_to_excerpt`（知识点找原文）；干扰项来自其他知识点；选项用题目 ID 做确定性打乱；判分在服务端。
- `app/scheduler/mastery.py`：掌握度加分/扣分/时间衰减 + 简化 SM-2（1 天 → 3 天 → 间隔 × ease；答错 30 分钟）。
- `app/scheduler/review.py`：今日队列（未练习优先、低分优先、到期早优先）与统计。
- 练习提交同时写 seekdb（练习记录、掌握度）与 PowerContext（task_state + 错题 weakness），两条链路各有 trace。
- 前端加“今日复习”页、开始 5 题 / 20 题模拟、结果列表与掌握度变化。

### 遇到的问题与处理

1. **不能手写题目**：手写题库不可扩展也无法证明来自资料。处理：题目答案只能是章节名或原文片段，解释里回链 `source_chunk_id`。
2. **选项顺序不能每次变**：会导致同一题截图/复核不一致。处理：以 `question_id` 为随机种子确定性打乱。
3. **干扰项不足**：资料少时可能凑不出 4 个选项。处理：同科优先、跨科补齐；不足 2 个则放弃该题，不编造。
4. **“到期”判断跨时区**：Python 存 naive UTC，SQL 却用本地 `NOW(6)`，导致刚练过的知识点仍算到期。处理：S6 统一改为 `UTC_TIMESTAMP(6)` / `UTC_DATE()`。

### 验证结果

- 生成 5 题全部来自真实 chunk；提交后每题返回 `mastery_before → mastery_after`、正确答案、解释、`source_chunk_id`、`next_review_at`。
- 答错后下次复习为 30 分钟后；答对按 1 天 / 3 天 / 间隔 × ease 递进。
- 今日统计能随练习变化，首页角标同步。

### 对应提交

`feat(qoder): S4 knowledge points, mastery and SM-2 review practice`（`98cd1b73`）

---

## S5 · 三页面交互、计划与演示闭环（2026-11-01）

### 目标

把已有能力做成一条普通人能点完的路径：资料库 → 问答 → 收尾 → 复习 → 计划 → 记忆核对。

### 实际做了什么

- 前端改为三页 SPA（今日复习 / 问答 / 资料库），原生 JS，无构建链；导航“今日复习”带到期数量角标。
- 问答页：模式切换、学科过滤、引用卡片、注入记忆、会话收尾、技术轨迹抽屉（按四层展示）。
- 今日复习页：统计卡、SM-2 队列、开始 5 题 / 20 题模拟、结果详情、生成 3 天计划。
- 资料库：文档列表、导入示例、上传并索引、删除；底部 PowerContext 记忆列表与统计。
- “演示模式”：一键导入种子资料并连续跑 3 轮问答，每轮收尾写记忆；第 3 轮展示前两轮记忆的效果。
- `POST /api/review/plan`：按实时队列生成计划并写入 `plan` memory。

### 遇到的问题与处理

1. **重复点击生成重复计划**：PowerContext 里出现两条一模一样的 `plan`。处理：生成前按文本比对近期 plan，相同则复用，返回 `reused=true`，UI 标“复用已有”。
2. **日期标题污染知识点名**：笔记标题“2026-10-25 复盘：正则化与过拟合”直接变成知识点名，出题选项很脏。处理：通用正则去掉日期前缀与“复盘/笔记/随记”，并重命名种子笔记里的“错题摘录与待办”。
3. **会话切换丢上下文**：演示模式结束后原会话被覆盖。处理：演示前保存、结束后恢复原 session。
4. **截图选择器写错**：测试脚本用 `.memory-item` 找不到记忆，误以为列表为空。实际类是 `.memory-row`；修正后确认 plan 记忆正常渲染。
5. **代码格式回退**：`updateQuizProgress()` 被压成一行，`git diff` 时发现并修回，避免后续维护困难。

### 验证结果

- 三页均可用鼠标完成主流程；桌面 1440 宽与窄屏布局均正常。
- 计划卡显示 trace ID、memory ID、队列知识点；重复点击返回同一 artifact ID。
- 技术轨迹抽屉能看到 seekdb 检索、PowerContext 读写、应用编排与 LLM（未配置时无该层）。
- 10 张最终截图覆盖问答、注入记忆、轨迹、复习前后、题目、结果、计划、资料库与记忆。

### 对应提交

`feat(qoder): S5 study plan, due badge and interactive review polish`（`3680a3ea`）

---

## S6 · 启动加固、时区修复与交付文档（2026-11-01）

### 目标

让仓库在干净环境里“双击就能跑”，并补齐 README、验收、网站文案、自检清单与截图。

### 实际做了什么

- 重写 `start_windows.bat` 与 `start_macos.sh`：先起应用并等 `/health`，再起 PowerContext 并等 `/health/ready` 为 `ready`，最后打开浏览器；macOS 用 trap 同时回收两个进程。
- 修复 SQL 时区：`NOW(6)` / `CURDATE()` 全部改为 `UTC_TIMESTAMP(6)` / `UTC_DATE()`（会话、队列、统计）。
- 增加 `scripts/verify.py`：一次跑完健康、导入、检索、问答、收尾、二次召回、出题判分、计划与轨迹断言。
- 增加 `docker/` 容器编排作为备选路径，并在 README 明确标注本机未验证。
- 产出 10 张 1440×1000 截图；重写 README；新增 `docs/verification.md`、`docs/website-content.md`、`docs/self-check.md`。

### 遇到的问题与处理

1. **PowerContext 启动顺序**：先起 PowerContext 时，嵌入探针在应用未监听时超时，之后一直 `degraded`；即使应用随后启动也不会自动恢复。处理：两个一键脚本都改为 app 先起，并在 README 解释原因。
2. **时区导致“练过仍到期”**：Python 写 `datetime.now(timezone.utc)`，SQL 用本地 `NOW(6)`；UTC+8 下练习记录比队列判断晚 8 小时，出现“今日已答 10、仍然 due 25”。处理：统一 UTC SQL；修复后 27 个知识点中 7 个已练习，due 正确变为 20。
3. **浏览器截图宽度受限**：自带浏览器工具视口固定约 454 px，无法展示桌面布局。处理：用无头 Chrome + CDP 以 1440×1000 截图，等待 toast（3.6 s）消失后再拍。
4. **重复截图出现 toast 遮挡**：生成计划/完成练习的提示浮层盖住内容。处理：统一等待 ≥4.2 s 后重拍。
5. **Docker 无法验证**：本机没有 Docker。处理：仍提供编排文件，但在 README 明确“未端到端验证”，主路径保持嵌入式一键启动，不声称已验证。

### 验证结果

- `start_windows.bat` 冷启动后 `/health` 的 `powercontext.ready=true`，`inference.embedding=ready`。
- 修复时区后今日统计与练习记录一致；截图 07 显示 20 待复习、10 已答、2 正确。
- 干净数据目录下按验收脚本可完整走通导入 → 问答 → 收尾 → 复习 → 计划。
- README、验收、文案、自检四份文档与截图齐备。

### 对应提交

`feat(qoder): S6 reliable startup, UTC scheduling and delivery docs`（`0bf26520`）

---

## S7 · 干净环境复现与证据归档（2026-11-01）

### 目标

从空数据目录完整复现一次，确认交付不是依赖已有运行状态；把原始日志、风险与未验证项写清楚，准备提交。

### 实际做了什么

- 停止两个服务，删除 `data/seekdb`、`data/powercontext`、`data/uploads`，保留模型缓存。
- 按 app → PowerContext 顺序启动，确认空库为 0 文档 / 0 chunk、PowerContext 为 `ready`。
- 运行 `scripts/verify.py`：11 步全部 PASS；3 文档 / 27 chunks；首轮收尾 3 条记忆；第二轮注入 3 条；3 题判分 0.5 → 0.4；计划连续两次复用同一 artifact；三层轨迹齐全。
- 运行 `scripts/evidence.py` 导出 seekdb 文档、掌握度、练习记录、轨迹与 PowerContext 原始条目。
- 将本次真实日志入库：`docs/samples/verify-clean-run.txt`、`docs/samples/evidence-clean-run.txt`。
- 新增 `docs/reproduction-log.md`：复现步骤、空库基线、验收结果、四项基本验收、五个评分风险与处理、未验证项。
- 修复会话摘要的问题重复：`/api/search` 与 `/api/ask` 对同一问题只差句末标点，`session_evidence` 改为按去标点后的文本去重。

### 遇到的问题与处理

1. **干净环境的“注入条数”比演示时少**：第二轮只注入 3 条，而演示会话可注入 10 条。原因不是逻辑退化，而是记忆总量不同。处理：验收脚本只断言“注入条数 > 0”与 kind 存在，不写死条数；复现文档解释差异。
2. **摘要里同一问题出现两次**：显式检索与问答各写一条 seekdb trace，文本只差句末问号。处理：去标点后去重，保留首次出现。
3. **截图数字与干净复现不一致**：截图来自更长的演示会话（17 条记忆、10 道练习），干净复现是 8 条记忆、3 道练习。处理：文档明确说明以界面结构与日志为准，不把截图当数据快照。
4. **Docker 与真实 LLM 无法在本机验证**：不伪造结果。处理：Docker 标注“未端到端验证”，LLM 标注“未配置真实 key，evidence 模式已验证”。

### 验证结果

- 空库启动正常，导入后 3 文档 / 27 chunks / 27 知识点。
- `verify.py` 全绿，退出码 0；原始日志与证据日志已入库。
- PowerContext 干净运行共 8 条记忆：`weakness` 4、`session_summary` 1、`profile` 1、`plan` 1、`task_state` 1。
- 摘要问题去重生效：只剩一条“正则化和过拟合是什么关系”。

### 对应提交

`fix(qoder): S7 clean-room verification and session query dedupe`
