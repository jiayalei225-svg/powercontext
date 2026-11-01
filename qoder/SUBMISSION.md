# PaperDesk 2.0 · 提交说明

## 赛题与分支

| 项目 | 内容 |
| --- | --- |
| 赛题 | Qoder × OceanBase 2026 · 基于 PowerContext / seekdb 的应用 |
| 上游分支 | `oceanbase/powercontext` → `2026-competition-ecosystem` |
| 提交仓库 | `https://github.com/jiayalei225-svg/powercontext` |
| 提交分支 | `2026-competition-ecosystem` |
| 项目目录 | `qoder/` |
| 项目网站 | `https://paperdesk-4qzym26fsnz.qoder.zone` |
| 网站可见性 | 任何人可访问（public） |

本轮修复提交：`（推送后填写）`。最终提交以 `2026-competition-ecosystem` 分支 HEAD 为准。

## 一句话介绍

PaperDesk 把 PDF 论文切成语义片段，用 seekdb 一次完成向量召回、全文召回、标量过滤和 RRF 融合；用 PowerContext 保存检索偏好与轨迹，让下一次检索自动带上你的口味。

## 交付清单

| 要求 | 交付 |
| --- | --- |
| 项目网站（Qoder Sites 发布） | `https://paperdesk-4qzym26fsnz.qoder.zone` |
| 代码仓库 | `https://github.com/jiayalei225-svg/powercontext/tree/2026-competition-ecosystem/qoder` |
| 运行说明 | [`README.md`](README.md) 的“快速开始” |
| 验证样例 | [`docs/verification.md`](docs/verification.md)、[`docs/verification/`](docs/verification) |
| Qoder 开发记录 | [`docs/qoder-records.md`](docs/qoder-records.md) |
| Qoder 账号 UID | `01a191a9-93d1-776f-b48c-c3727d164e84` |
| 配置占位 | [`.env.example`](.env.example)，无真实密钥 |

## seekdb 的实际使用

seekdb 不是“可选演示”，而是论文片段的唯一存储与检索引擎：

- 每篇 PDF 被切成 5-6 个片段，写入同一个集合 `paper_chunks_v2_bge_zh`；
- 检索调用 `collection.hybrid_search(...)`，同时传入：
  - `query`：全文召回与 `$contains` 字面锚点；
  - `knn`：`bge-small-zh-v1.5` 向量召回；
  - `where`：年份、会议、方向、开源、单篇过滤；
  - `rank`：内置 RRF（`rank_window_size=60`，`rank_constant=60`）；
- 上传、删除、统计、详情都直接读写 seekdb，没有第二套索引；
- 原始 PDF 保存在 `data/uploads/`，论文详情页可直接打开，验收逐篇检查返回 `%PDF`。

代码入口：`backend/app/index.py`、`backend/app/pdf.py`。

## PowerContext 的实际使用

PowerContext 不是“记录一条日志”，而是偏好与轨迹的唯一持久层：

- 保存偏好：`POST /v1/memory/remember`，`kind=preference`，文本带 `paperdesk2/prefs/v1|` 标记；
- 读取偏好：`POST /v1/atomic-memory/list`，`kind=preference`，沿 `next_cursor` 翻完所有页，按 `saved_at` 取最新；
- 每次检索：写入 `kind=progress`、`paperdesk2/trace/v1|` 标记的轨迹；
- 记忆默认值在检索计划中逐字段合并，显式条件永远优先；
- 界面显示 artifact ID 与 revision，证明偏好确实写入并能追溯；
- 完全停止并重启 PowerContext 与 PaperDesk 后，scope、四字段与 artifact 均保持不变。

代码入口：`backend/app/memory.py`、`backend/app/recall.py`。

### 读回证据

- `GET /api/preferences?fresh=1`：绕过应用内 12 秒缓存，回源读取；
- `scripts/accept.py`：绕过 PaperDesk，直接分页读取 PowerContext，并比对 artifact ID 与四字段；
- `docs/verification/powercontext-readback.json`：直读响应；
- `docs/verification/restart-readback.json`：完全重启前后的对照，`match=true`。

## 运行

Windows：

```powershell
cd qoder
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

macOS / Linux：

```bash
cd qoder
bash scripts/start.sh
```

默认地址 `http://127.0.0.1:8080`。首次运行会安装依赖、下载本地 BGE 模型、启动 PowerContext 并导入 5 篇演示 PDF。脚本固定 `POWERCONTEXT_HOME=runtime/powercontext`，并检查 18000 端口是否属于同一 scope。

## 验证结果

| 项目 | 结果 |
| --- | --- |
| 单元测试 | 15 passed |
| 端到端验收 | 24 / 24 PASS |
| 演示语料 | 5 篇 / 26 片段 |
| 混合检索 | 6 个片段，`strategy=hybrid` |
| 记忆偏好 | 保存 / 清缓存读回 / 绕过应用直读 / 自动应用 / 显式覆盖 / 清除 / 完全重启读回 全部通过 |
| 最终 artifact | `art_6348613106ea4529a1c8745f10393a45`（scope `scp_2gs37bhwx70f9gqx00jr6z7c82`） |
| 导出 | Markdown 2186 字节 + CSV 1648 字节（UTF-8 BOM） |

复现：

```bash
cd qoder
pytest
python scripts/accept.py --base http://127.0.0.1:8080
```

真实运行截图与报告见 `docs/verification/`。

## 网站形态说明

本站是 **Qoder Sites 上公开可访问的项目介绍页**，不是在线版应用：

- 页面展示真实运行截图、架构、验收报告链接与复现命令；
- Qoder Sites 当前为静态托管，无法运行 Python、seekdb 本地引擎和 PowerContext 服务；
- 完整应用按 README 在本机启动，不依赖云服务与 API Key；
- 站点不伪造“在线检索”或“在线记忆”，所有截图与 artifact 均来自本机真实运行。

## Qoder 开发

- 主要开发工作在本 Qoder 会话完成，账号 UID 见上表；
- 会话截图：`site/web/assets/qoder-session-final.png`；
- 开发记录：`docs/development-log.md`；
- 代码、测试、验收、站点内容均在本会话内生成。

## Qoder Sites 发布记录

| 项目 | 值 |
| --- | --- |
| 项目 ID | `01a191be-acc7-7d2d-8403-aae09c693514` |
| 站点 ID | `01a191be-accb-777c-927c-adb7a1c58023` |
| 访问地址 | `https://paperdesk-4qzym26fsnz.qoder.zone` |
| 访问模式 | public |
| 本轮发布操作 | 见下方“本轮重新发布”记录 |

### 本轮重新发布

`（发布后填写 action ID、发布时间与验证结果）`

## 安全与合规

- 仓库不包含 `.env`、`config/powercontext.env`、任何真实 API Key 或密码；
- `.env.example` 只保留空值与本地地址；
- PDF、索引和记忆数据均在本地，演示数据为原创生成；
- 站点为静态项目介绍，不含用户数据与后端凭据。

## 已知限制

- 项目网站是项目介绍页，不是在线版应用；完整应用需本机启动；
- 演示语料为 5 篇原创示例论文，用于复现链路；
- 本地 ONNX 模型首次加载需要数秒；
- 扫描版 PDF 需要外部 OCR；
- 单机单用户，未实现登录体系。
