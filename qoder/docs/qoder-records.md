# Qoder 开发记录

## 账号与工作区

| 项目 | 值 |
| --- | --- |
| Qoder 账号 UID | `01a191a9-93d1-776f-b48c-c3727d164e84` |
| 工作区 | `C:\Users\jyl25\Documents\Qoder\2026-10-31\5ae0bb21` |
| 主要开发目录 | `rebuild/qoder` |
| 开发时间 | 2026-10-31 至 2026-11-01 |
| Qoder 客户端 | Qoder CN 桌面端 |

## 会话截图

下图于 2026-11-01 在 Qoder 桌面端截取，显示本项目的重建任务、Qoder Sites 发布、工具调用、终端命令与验证过程：

![Qoder 会话](../site/web/assets/qoder-session-final.png)

截图中的关键信息：

- 左侧工作区为“交付结果”，对应本项目；
- 会话记录包含后端、前端、样例数据、站点发布、分支推送与验收的完整重建过程；
- 执行状态显示工具调用次数、终端命令与耗时；
- 右侧为本次会话的实际任务执行流，不是后期制作的界面图。

发布站点与推送分支的记录见本页末尾与 `SUBMISSION.md`。

## 在本会话中完成的工作

### 代码

- 从空目录重建 `backend/app` 的 8 个模块；
- 重建 React 19 + TypeScript + Vite 前端，包含检索、文献库、记忆三个页签；
- 生成 5 篇原创演示 PDF 与 26 个语料片段；
- 编写启动脚本、导入脚本、命令行工具和验收脚本；
- 编写 15 个单元测试。

### 真实运行与验收

- 启动独立 PowerContext 实例；
- 在浏览器中完成上传、检索、打开论文、保存偏好、自动应用偏好、删除、导出；
- 15 个单元测试通过；
- 24 项端到端检查通过；
- 证据见 [verification.md](verification.md) 与 `verification/` 目录。

### 2026-11-01 的记忆读回修复

这一轮针对“数据或记忆无法正确读回和复用”的反馈，逐个排查并修复了以下链路：

1. **PowerContext 列表顺序**：`/v1/atomic-memory/list` 的条目库存按 artifact 排列，不是按时间倒序。原实现只读第一页，轨迹积累后会漏掉最新偏好。现在按 `kind=preference` / `kind=progress` 过滤，沿 `next_cursor` 翻完所有页，再按 `saved_at` 取最新。
2. **强制新鲜读取**：新增 `GET /api/preferences?fresh=1`，绕过 12 秒进程缓存，直接回到 PowerContext。
3. **绕过应用直读**：验收脚本直接调用 PowerContext 接口，比对 artifact ID 与四字段内容，证明不是应用缓存的假象。
4. **原始 PDF 读回**：`seed.py` 和重复上传都会把 PDF 复制到 `data/uploads/`，`GET /api/papers/{id}/file` 返回 `%PDF`；验收逐篇检查 5/5。
5. **启动配置一致**：`start.ps1` / `start.sh` 与手动启动都固定 `POWERCONTEXT_HOME=runtime/powercontext`，并检查 18000 端口是否属于同一 scope，避免把记忆写到另一套数据库。
6. **验收后不留空记忆**：`accept.py` 先验证清除，再写回四条最终偏好；报告记录 `final_artifact`，重启对照写入 `restart-readback.json`。
7. **完全重启验证**：停止 PowerContext 与 PaperDesk，重新启动后不经过写入接口，scope、四字段与 artifact 全部不变。

### 文档与网站

- README、架构、API、验收、开发记录；
- Qoder Sites 项目网站，使用真实运行截图；
- 站点明确标注为项目介绍页，不运行在线后端；截图、artifact 与验收数字均来自本机真实运行；
- 站点通过 Qoder Sites 发布并验证公开访问。

## 发布与提交记录

| 项目 | 值 |
| --- | --- |
| 上轮实现提交 | `1131a2714ac648ab57574eacf33197dc51a1236d` |
| 本轮修复提交 | `e9b0e5efde77f7b48f3254bd8b519d337405c6dd` |
| 本轮准备 / 发布操作 | `59de7ede-1971-41d0-9aa2-e98b992fc84d` / `01a19533-96f8-763b-8b87-5eb319971f28` |
| 站点地址 | `https://paperdesk-4qzym26fsnz.qoder.zone` |
| Qoder Sites 项目 / 站点 | `01a191be-acc7-7d2d-8403-aae09c693514` / `01a191be-accb-777c-927c-adb7a1c58023` |
| 公开状态 | `public`，HTTP 200 |

## 如何核验

1. 打开仓库 `qoder/` 目录，查看 `backend/app` 与 `frontend/src` 的实现；
2. 按 README 一条命令启动，执行 `scripts/accept.py`，复现 24 项验收；
3. 查看 `docs/verification/report.json` 中的 `generated_at`、`final_scope`、`final_artifact`；
4. 查看 `docs/verification/powercontext-readback.json` 与 `restart-readback.json`，核对完全重启前后的偏好；
5. 对比 `site/web/assets/` 中的运行截图与本地页面；
6. 通过 Qoder 账号 UID 关联本次开发会话。

## 说明

- 截图由 Qoder 桌面窗口直接捕获，未拼接、未修改内容；
- 会话中的路径、命令、测试结果均可在本地工作区复核；
- 项目网站使用 Qoder Sites 发布，发布记录见 `SUBMISSION.md`；
- 站点是公开的项目介绍页，不是在线版应用；Qoder Sites 静态托管无法运行 Python、seekdb 本地引擎与 PowerContext 服务，完整应用按 README 在本机启动。
