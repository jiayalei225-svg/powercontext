# PaperDesk · 文献检索工作台

> 参赛提交说明（网站/仓库/UID/验证步骤/材料索引）见 [SUBMISSION.md](SUBMISSION.md)。

一个本地优先的文献阅读台：把 PDF 丢进来，按你自己的习惯检索，命中结果能精确到**第几页的哪一段**。

面向的场景很具体——读研、写综述、跟课题时，文献散在十几个文件夹里，文件名记不住，只记得"那篇讲图神经网络过平滑的"。通用搜索要么搜不到，要么给个整篇 PDF 让你自己翻。PaperDesk 做三件事：

1. **把文献变成可检索的段落**：按页切块，每段都带着论文标题、年份、会议、页码，检索结果直接给原文片段，不给你一个文件让你从头找。
2. **混合检索**：向量语义 + 全文关键词 + 元数据过滤（年份 / 会议 / 领域 / 是否有代码），三路结果在 seekdb 内部用 RRF 融合。
3. **记住你的检索习惯**：常用会议、起始年份、是否只看有代码的论文，存进 PowerContext，下次检索自动套用，并在界面上告诉你"这次按记忆改了什么"。

## 两个指定技术怎么分工

- **seekdb** 负责"东西存在哪、怎么找"：文献分块、向量、元数据、全文索引全部落在一个嵌入式 seekdb 实例里（`data/seekdb/`，无需 Docker、无需单独装服务）。检索走 `hybrid_search`，向量 KNN、`$contains` 全文匹配、标量 `where` 过滤三路在库内融合，不是应用层拼结果。
- **PowerContext** 负责"你是谁、你习惯什么"：用户偏好和每次检索记录以带版本号的 Memory 条目写入 PowerContext（`/v1/memory/remember`），检索前读出最新偏好并转成 seekdb 的过滤条件。PowerContext 挂了，检索照常可用，只是不带记忆——这是刻意的降级设计。

两者的因果链是可验证的：**同一句 query，写入偏好前后结果集不同**，`scripts/verify.py` 会把这条链路跑一遍并逐项断言（见下文"验收样例"）。

## 性能

一次检索的实测中位耗时（12 段样例，Windows 11 / Python 3.13）：**约 115 ms**。
优化前约 6.5 s，原因是每次检索新建 3 个 PowerContext HTTP 连接（本机建连约 1.5 s）
并做 3 次 `$contains` 稀有度探测。现在改为连接池 + 偏好 TTL 缓存 + 语料缓存，
详见 `docs/architecture.md` 的"性能"一节。

## 运行环境的一个坑：数据目录不能含中文

seekdb 的原生层打不开非 ASCII 路径。仓库放在 `C:\Users\张三\OneDrive\文档\...` 这类路径时，
`config.py` 会自动把数据目录回退到 `%LOCALAPPDATA%\PaperDesk\data` 并打印一行提示；
也可以用 `PAPERDESK_DATA_DIR` 显式指定一个纯英文路径。上传文件与 seekdb 数据都会放在那里。

## 功能

- 上传 PDF / Markdown / TXT，自动解析标题、页数、年份，按页切成约 360 字的块（重叠 60 字）
- 三栏界面：左侧文献库，中间检索与结果，右侧记忆面板
- 检索过滤器：年份区间、会议多选、领域、限定单篇、是否有开源代码
- 结果卡片显示：论文、年份、会议、页码、命中片段（关键词高亮）、相似度
- 记忆面板：编辑默认偏好（写入 PowerContext）、查看记忆条目与最近检索
- 重复上传按文件内容哈希去重（409），扫描版无文本 PDF 明确报错（422）

## 技术栈与版本

后端：

- Python 3.13（3.10–3.13 均可；`pylibseekdb` 提供 cp312-abi3 轮子）
- `pyseekdb==1.4.0.post1` + `pylibseekdb==1.4.0.post2`（嵌入式 seekdb）
- `powercontext[server]==1.4.1`（记忆服务，内置 SQLite 后端）
- `fastapi>=0.115` / `uvicorn[standard]>=0.34`
- `pymupdf>=1.24`（PDF 解析）
- `httpx>=0.28`（PowerContext 客户端）

前端：

- React 19.2 / TypeScript 5.9 / Vite 7.1 / Tailwind CSS 4.1
- 仓库内已提交构建产物 `frontend/dist/`，评委无需装 Node 即可直接跑后端访问界面

向量模型：

- 默认本地 ONNX，中文 BGE 小模型 `Xenova/bge-small-zh-v1.5`（512 维，约 90 MB）
- 首次启动自动下载，默认走 `https://hf-mirror.com` 镜像；下载失败时自动降级到 pyseekdb 自带的英文 MiniLM，应用仍可启动
- 也可切换为任意 OpenAI 兼容的 Embeddings 接口（见配置说明）

## 目录结构

```
backend/
  run.py                 # uvicorn 入口，127.0.0.1:8080
  app/
    main.py              # FastAPI 路由、启动预热、静态页面托管
    config.py            # .env 读取与数据目录
    ingest.py            # PDF 解析、按页分块、论文 ID
    store.py             # seekdb 集合、写入、删除、混合检索
    search.py            # 关键词抽取、记忆偏好合并、检索编排
    memory.py            # PowerContext 客户端（偏好 / 检索留痕）
    embeddings.py        # 本地 BGE / 远程 Embeddings 适配
frontend/
  src/                   # React 界面；dist/ 是已构建产物
scripts/
  start.ps1 / start.sh   # 一键启动（建环境、装依赖、起 PowerContext、起 API）
  make_samples.py        # 生成 4 篇可复现的样例阅读笔记 PDF
  seed.py                # 把样例灌进运行中的库
  verify.py              # 验收脚本：14 项断言，输出证据
docs/
  architecture.md        # 组件分工、seekdb 检索、性能数据
  development-log.md     # 需求拆解、实现、踩坑与修复
  verification-log.txt   # 本机 14/14 的完整输出
  qoder-sites.md         # Qoder Sites 发布记录（ID、链路、公开访问）
  qoder-records/         # Qoder 桌面端/CLI/站点记录
data/
  samples/               # 样例 PDF（由 make_samples.py 生成）
  seekdb/  uploads/      # 运行时数据，已被 .gitignore 忽略
```

## 快速开始

### 环境要求

- Python 3.10 及以上（Windows 建议 3.12/3.13 64 位）
- 首次启动需要联网下载约 90 MB 的向量模型（走镜像，国内可直连）
- 不需要 Docker，不需要 MySQL，不需要单独部署 seekdb
- 可选：Node.js 20+，仅在你想改前端时需要
- 国内网络装依赖慢时，可先设置镜像再启动：
  `$env:PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"`

### 方式一：一键启动（Windows PowerShell）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

脚本会依次完成：创建 `.venv` → 安装 `requirements.txt` → 从 `.env.example` 生成 `.env` → 生成 `config/powercontext.env` → 启动 PowerContext 并等它 ready → 启动 PaperDesk API。

看到下面两行即为就绪：

```
  PaperDesk  ->  http://127.0.0.1:8080
  PowerContext->  http://127.0.0.1:8000  (PID xxxxx)
```

另开一个 PowerShell 窗口，导入样例文献：

```powershell
.\.venv\Scripts\python.exe scripts\seed.py
```

然后浏览器打开 <http://127.0.0.1:8080>。

### 方式二：一键启动（macOS / Linux / WSL）

```bash
bash scripts/start.sh
```

同样会建环境、起 PowerContext、起 API。脚本退出时（Ctrl+C）会自动停掉它启动的 PowerContext。首次使用另开终端执行：

```bash
.venv/bin/python scripts/seed.py
```

### 方式三：手动分步（想看清楚每一步时）

```bash
# 1. 虚拟环境与依赖
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip      # Windows
.venv/Scripts/python -m pip install -r requirements.txt

# 2. 配置（全部是占位值，按需改）
cp .env.example .env

# 3. 生成 PowerContext 配置
.venv/Scripts/powercontext.exe config init --template --output config/powercontext.env

# 4. 起 PowerContext（先加载它自己的环境变量）
set -a; . config/powercontext.env; set +a
.venv/Scripts/powercontext.exe server run &
curl http://127.0.0.1:8000/health/ready

# 5. 起 PaperDesk
.venv/Scripts/python backend/run.py
```

第 4 步在 **Git Bash** 里执行时有一个坑：MSYS 会把 `/mcp` 这类参数改写成本地路径，PowerContext 会报 "MCP path must be an absolute non-root path"。解决方法是先关闭路径转换：

```bash
export MSYS2_ENV_CONV_EXCL="POWERCONTEXT"
export MSYS_NO_PATHCONV=1
```

PowerShell 和命令提示符没有这个问题。

### 只改前端时

后端保持运行，另开终端：

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173，/api 已代理到 8080
npm run build      # 产出 frontend/dist，后端会自动托管
```

## 配置说明

所有配置都在 `.env`，示例文件 `.env.example` 里**只有占位值，没有任何真实凭据**。

```
PAPERDESK_DATA_DIR=./data
EMBEDDING_MODE=local
# EMBEDDING_API_BASE=https://your-endpoint.example.com/v1
# EMBEDDING_API_KEY=sk-xxxxxxxx
# EMBEDDING_MODEL=text-embedding-v3
# EMBEDDING_DIM=1024
POWERCONTEXT_URL=http://127.0.0.1:8000
POWERCONTEXT_TIMEOUT=5
PAPERDESK_MEMORY_ENABLED=true
```

- `EMBEDDING_MODE=local`：默认，零配置，离线可用（仅首次下载模型）。
- `EMBEDDING_MODE=api`：切到 OpenAI 兼容接口，四项需同时填写。注意切换后集合名会变（`paper_chunks_api_<model>`），需要重新导入文献，避免维度冲突。
- `POWERCONTEXT_URL`：PowerContext 地址；把它指错或停掉，检索仍可用，界面显示"记忆未连接"。
- 想换模型下载源：设置环境变量 `HF_ENDPOINT`，默认 `https://hf-mirror.com`。

样例数据和 `data/seekdb/` 都是可变状态。重做干净演示时，先停掉 API，删除 `data/seekdb/` 和 `data/uploads/`，再重新 `seed.py`；偏好清空用 `python scripts/verify.py --reset` 或界面上的记忆面板。

## 验收样例（可逐步复现）

准备：API 与 PowerContext 均已启动，`scripts/seed.py` 已导入 4 篇样例（共 12 段）。

样例文献均由 `scripts/make_samples.py` 生成，是自己撰写的阅读笔记，不涉及版权：

- Transformer 阅读笔记（NeurIPS 2017，自然语言处理，有代码）
- RAG 阅读笔记（NeurIPS 2020，信息检索，有代码）
- 图神经网络阅读笔记（ICLR 2019，图学习，无代码）
- PEFT 阅读笔记（ICLR 2021，模型训练，有代码）

执行：

```bash
.venv/Scripts/python scripts/verify.py --reset
```

脚本会做 7 组、共 14 项检查，关键步骤如下。

1. **健康检查**：确认 seekdb 里有文献和分段、嵌入模型已加载、PowerContext 已连接。
2. **文献库**：确认至少 4 篇，打印每篇的会议与年份。
3. **第一次检索（记忆为空）**：用 `图神经网络为什么会过平滑` 检索。
   - 期望：有命中，共 12 段；`memory_notes` 为空（没有套用任何记忆）。
   - 期望：首条命中《图神经网络》第 2 页。
   - 脚本会打印全文分支实际使用的关键词。这个词是从 query 的实词里挑**在当前语料中出现最少**的一个（本例是"平滑"），避免用"神经网络"这类高频词把全文匹配变成噪声。
4. **写入偏好**：通过 `PUT /api/preferences` 把偏好写进 PowerContext——2020 年起、只看 NeurIPS、必须有代码、关注图神经网络、阅读习惯"先看摘要和方法"。
   - 期望：返回 PowerContext 的 `artifact_id` 与 `revision`，证明写的是记忆条目而不是本地文件。
5. **第二次检索（同一句 query）**：
   - 期望：`memory_notes` 非空，逐条说明这次按记忆改了什么。
   - 期望：结果数量从 12 收缩到 3，且每一条都满足 NeurIPS / 2020 及以后 / 有代码。
6. **记忆留痕**：`GET /api/memory` 能看到至少 1 条偏好条目、至少 2 条检索进度条目。
7. **跨会话复用**：重新读取偏好，内容与写入的一致。

本机实测输出（14/14）：

```
== 1. 服务健康 ==
  [PASS] seekdb 可用 — 4 篇 / 12 段
  [PASS] 嵌入模型 — bge-small-zh-v1.5 (local)
  [PASS] PowerContext 已连接 — http://127.0.0.1:8000
== 3. 第一次检索（记忆为空）==
  [PASS] 命中结果 — 12 段
  [PASS] 首条命中《图神经网络》第 2 页 — 阅读笔记：图神经网络与消息传递框架 p.2
  [PASS] 未应用记忆偏好 — memory_notes 为空
      关键词（全文分支）：平滑
== 5. 第二次检索（同样的 query，记忆生效）==
  [PASS] 检索时自动应用了偏好 — 3 条
  [PASS] 结果全部满足记忆约束 — 3 段，违规 0 段
  [PASS] 结果数量因过滤而收缩 — 12 → 3 段
结果：14/14 项通过
```

界面上的同一过程：右侧记忆面板填写偏好并保存，中间检索同样的句子，结果上方的黄色提示条会列出"按记忆默认只看 2020 年以后的文献 / 限定 NeurIPS / 排除了没有开源代码的论文"。

## 接口一览

- `GET /api/health`：seekdb 统计、嵌入模型、PowerContext 连接状态
- `GET /api/papers`：文献列表（标题、年份、会议、领域、页数、分段数）
- `POST /api/papers/upload`：multipart 上传，附加 venue / field / year / has_code
- `DELETE /api/papers/{paper_id}`：删除该论文所有分段
- `POST /api/search`：`{query, year_from, year_to, venues, field, paper_id, has_code, limit}`，返回结果、实际关键词、过滤条件、记忆提示
- `GET /api/memory`：记忆条目、偏好、最近检索
- `GET /api/preferences` / `PUT /api/preferences`：读写偏好；PowerContext 不可用时读写分别返回降级结果 / 503

## 数据与代码来源声明

- `data/samples/*.pdf`：由 `scripts/make_samples.py` 用 PyMuPDF 现场生成的中文阅读笔记，内容为本项目自撰，未复制任何论文原文或第三方数据集。
- 依赖库均为开源项目，按原许可证使用：seekdb / pyseekdb（OceanBase，Apache-2.0）、PowerContext（Apache-2.0）、FastAPI（MIT）、PyMuPDF（AGPL-3.0）、jieba（MIT）、React / Vite / Tailwind CSS（MIT）。
- 本项目未内嵌任何第三方代码片段；如后续引入，将在此注明来源与改动。
- 仓库中不含任何真实 API Key、密码或凭据，`.env.example` 全部为占位值；`.env`、`data/seekdb/`、`data/uploads/` 已在 `.gitignore` 中排除。

## 常见问题

- **首次检索很慢**：模型在首次使用时加载。本项目已在 FastAPI 启动阶段预热，正常启动完成后第一次检索不再等待。
- **`seekdb_open failed` / 日志文件被占用**：上一个 API 进程还没退。先确认并结束监听 8080 的 python 进程，再重启；不要直接删除正在被占用的 `data/seekdb/`。
- **8080 / 8000 被占用**：API 端口用 `PAPERDESK_PORT` 改（例如 `$env:PAPERDESK_PORT=18080`），
  PowerContext 端口在 `config/powercontext.env` 的 `POWERCONTEXT_SERVER_HTTP_PORT` 改，
  同时把 `.env` 的 `POWERCONTEXT_URL` 指到新端口；`seed.py` / `verify.py` 用 `--api` 指到新端口。
- **`{"detail":"There was an error parsing the body"}`（用 curl 发中文）**：Git Bash 的编码问题，用 Python `httpx` 或前端页面发请求即可。
- **上传扫描版 PDF 报 422**：当前不做 OCR，只接受带文本层的文件。
- **界面显示"记忆未连接"**：PowerContext 没起或地址不对。检索本身不受影响。

## 参赛提交信息

- 项目网站：<https://paperdesk-4qzym26fsnz.qoder.zone>（Qoder Sites，公开访问，未登录可打开）
- 代码仓库：<https://github.com/jiayalei225-svg/powercontext/tree/2026-competition-ecosystem/qoder>
- 提交分支：`2026-competition-ecosystem`（commit 以 `git rev-parse HEAD` 为准）
- Qoder 账号 UID：`01a191a9-93d1-776f-b48c-c3727d164e84`
- 开发记录：`docs/development-log.md`、`docs/qoder-sites.md`、`docs/qoder-records/`
- 验证记录：`docs/verification-log.txt`（14/14）
