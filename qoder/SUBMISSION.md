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

最终提交 commit 以分支 HEAD 为准；实现提交为 `1131a2714ac648ab57574eacf33197dc51a1236d`，之后仅追加文档与站点记录。

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
- 上传、删除、统计、详情都直接读写 seekdb，没有第二套索引。

代码入口：`backend/app/index.py`。

## PowerContext 的实际使用

PowerContext 不是“记录一条日志”，而是偏好与轨迹的唯一持久层：

- 保存偏好：`POST /v1/memory/remember`，`kind=preference`，文本带 `paperdesk2/prefs/v1|` 标记；
- 读取偏好：遍历 `POST /v1/memory/entries/list`，取最新版本；
- 每次检索：写入 `kind=progress`、`paperdesk2/trace/v1|` 标记的轨迹；
- 记忆默认值在检索计划中逐字段合并，显式条件永远优先；
- 界面显示 artifact ID 与 revision，证明偏好确实写入并能追溯。

代码入口：`backend/app/memory.py`、`backend/app/recall.py`。

## 运行

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

macOS / Linux：

```bash
bash scripts/start.sh
```

默认地址 `http://127.0.0.1:8080`。首次运行会安装依赖、下载本地 BGE 模型、启动 PowerContext 并导入 5 篇演示 PDF。

## 验证结果

| 项目 | 结果 |
| --- | --- |
| 单元测试 | 11 passed |
| 端到端验收 | 19 / 19 PASS |
| 演示语料 | 5 篇 / 26 片段 |
| 混合检索 | 6 个片段，`strategy=hybrid` |
| 记忆偏好 | 保存 / 自动应用 / 显式覆盖 / 清除 全部通过 |
| 导出 | Markdown + CSV（UTF-8 BOM） |

复现：

```bash
pytest
python scripts/accept.py --base http://127.0.0.1:8080
```

真实运行截图与报告见 `docs/verification/`。

## Qoder 开发

- 主要开发工作在本 Qoder 会话完成，账号 UID 见上表；
- 会话截图：`docs/assets/qoder-session-final.png`；
- 开发记录：`docs/development-log.md`；
- 代码、测试、验收、站点内容均在本会话内生成。

## Qoder Sites 发布记录

| 项目 | 值 |
| --- | --- |
| 项目 ID | `01a191be-acc7-7d2d-8403-aae09c693514` |
| 站点 ID | `01a191be-accb-777c-927c-adb7a1c58023` |
| 访问地址 | `https://paperdesk-4qzym26fsnz.qoder.zone` |
| 访问模式 | public |
| 发布状态 | `publication_completed`，`published=true`，`lifecycle=active` |
| prepare action | `1071b22a-c44a-4d9e-a580-cdf785f7b5ae` |
| artifact 校验操作 | `01a194f7-0744-733f-a366-081cb65f2ce9`（succeeded） |
| 发布操作 | `01a194f7-3006-7bb3-8612-91bdda581481`（succeeded, committed） |
| 发布时间 | 2026-11-01 10:36 |
| 公开验证 | 首页、样式表与最新截图均返回 HTTP 200，页面包含最终发布内容 |

## 安全与合规

- 仓库不包含 `.env`、`config/powercontext.env`、任何真实 API Key 或密码；
- `.env.example` 只保留空值与本地地址；
- PDF、索引和记忆数据均在本地，演示数据为原创生成；
- 站点为静态项目介绍，不含用户数据与后端凭据。

## 已知限制

- 演示语料为 5 篇原创示例论文，用于复现链路；
- 本地 ONNX 模型首次加载需要数秒；
- 扫描版 PDF 需要外部 OCR；
- 单机单用户，未实现登录体系。
