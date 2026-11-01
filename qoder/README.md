# StudyCoach · 个人学习与复习教练

把散落在讲义、笔记和论文里的知识点变成可检索、可复习、会记住你的学习工作台。

当前阶段：**S1 骨架**。服务、目录、数据模型、启动脚本已就位；导入、混合检索、记忆注入、复习调度会在 S2–S5 逐层接入。未接通的接口会明确返回“未实现”，不会伪造结果。

## 这个项目解决什么

三件事同时成立才算有用：

- 资料能按语义找到原文，而不是只靠 Ctrl+F。
- 复习有调度，会的不会重复看，不会的不会被躲开。
- 助手记得你的偏好和错因，不用每次重新交代背景。

## 快速启动

Windows：

```
双击 start_windows.bat
```

macOS：

```
chmod +x start_macos.sh
./start_macos.sh
```

首次运行会创建 `.venv`、安装 `requirements.txt`、从 `.env.example` 复制 `.env`，然后监听 `http://127.0.0.1:8090`。

打开浏览器访问 `http://127.0.0.1:8090`，页面右上角显示“后端正常”即表示 S1 通过。

## 验证 S1

1. 执行启动脚本，确认终端出现 `Uvicorn running on http://127.0.0.1:8090`。
2. 打开首页，确认标题、三张模块卡片和“后端正常”状态。
3. 访问 `http://127.0.0.1:8090/health`，应返回 `status: ok`、`stage: S1`，并列出 seekdb 路径与 PowerContext 地址。
4. 访问 `http://127.0.0.1:8090/docs`，能看到 FastAPI 自动生成的接口文档。

## 目录

```
qoder/
  app/
    api/           HTTP 路由（当前只有 /health）
    ingest/        导入与切块（S2）
    retrieval/     向量 + 全文 + 过滤融合（S2）
    memory/        PowerContext 记忆读写（S3）
    scheduler/     掌握度与 SM-2 调度（S4）
    seekdb/        集合与关系表 schema（S1 定义，S2 接入）
    trace/         技术轨迹模型（S2 落库）
    web/           原生 HTML/CSS/JS 前端
  data/seed/       可导入的种子资料（S2）
  docs/            验证样例、开发记录、网站文案（S6）
  scripts/         PowerContext 启动脚本
  archive/         S1 之前归档的 PaperDesk 项目，不参与新项目运行
```

## 数据模型

seekdb 侧分两种形态，共用同一个嵌入式数据库目录：

- `study_chunks` collection：原文块、向量、全文索引与 `doc_id / doc_title / subject / section / page / chunk_id` 元数据，供混合检索使用。
- `study_*` 关系表：文档、知识点、知识点与 chunk 关联、题库、练习记录、掌握度、会话、用户、技术轨迹。分数排序和聚合走这些表。

PowerContext 侧定义五种 memory kind：

- `profile`：学习偏好
- `weakness`：薄弱点与错因
- `session_summary`：会话摘要
- `plan`：学习计划
- `task_state`：任务进展

每条记忆首行是 `[kind=...][subject=...][topic=...][at=...]`，正文保持自然语言。原因是 PowerContext 的检索接口没有 kind 过滤参数，应用层需要靠这行元信息做 kind 感知的召回。

## PowerContext 单独启动

```
Windows: scripts\start_powercontext.bat
macOS:   ./scripts/start_powercontext.sh
```

默认监听 `http://127.0.0.1:8000`，数据落在 `qoder/data/powercontext/`。S3 会把两个服务串进同一个启动流程。

## 说明

- 所有密钥只出现在 `.env.example` 的占位值里，`.env` 已被 git 忽略。
- 旧版 PaperDesk 项目完整保留在 `qoder/archive/paperdesk/`，历史 commit 仍可查；新项目不引用它的代码或数据。
- Docker 备选部署与详细排错在 S6 的 README 中补齐。
