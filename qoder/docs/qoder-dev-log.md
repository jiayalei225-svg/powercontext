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
