# 开发记录

本记录对应 `2026-competition-ecosystem` 分支 `qoder/` 目录的当前实现。主要开发工作在 Qoder 会话中完成，时间跨度 2026-10-31 至 2026-11-01。

## 1. 目标与约束

- 做一个中文文献检索工作台，而不是通用聊天界面；
- seekdb 必须承担核心检索：向量召回、全文召回、标量过滤与融合排序；
- PowerContext 必须承担核心记忆：偏好跨会话保存并自动应用；
- 所有数据本地保存，不依赖云服务；
- 仓库只出现占位配置，不提交任何真实密钥；
- 交付物包含可运行代码、样例、测试、验收报告、项目网站和 Qoder 开发记录。

## 2. 里程碑

### 2026-10-31

1. **确认上游与目录**
   - 基于 `oceanbase/powercontext` 的 `2026-competition-ecosystem` 分支；
   - 竞赛代码统一放在 `qoder/`，保留仓库内其他赛道目录。

2. **后端骨架**
   - `settings.py`：环境变量读取、ASCII 数据目录回退；
   - `embedding.py`：本地 BGE 中文模型与 OpenAI 兼容接口双模式；
   - `pdf.py`：PyMuPDF 抽取、头部元数据、句读感知分块；
   - `index.py`：seekdb 集合与 `hybrid_search`；
   - `memory.py`：PowerContext 偏好与轨迹协议；
   - `recall.py`：词项、字面锚点、记忆合并、片段摘要；
   - `serialize.py`：Markdown / CSV；
   - `server.py`：FastAPI 路由与静态托管。

3. **前端**
   - React 19 + TypeScript + Vite；
   - 检索 / 文献库 / 记忆三个页签；
   - 检索计划卡、原文片段高亮、论文抽屉、拖拽上传、偏好表单；
   - 响应式布局与移动端适配。

4. **样例与脚本**
   - 用 PyMuPDF 生成 5 篇原创中文示例论文（含标题、作者、会议、年份、方向、代码链接）；
   - `scripts/seed.py` 幂等导入；
   - `scripts/pd.py` 命令行客户端；
   - `scripts/start.ps1` / `scripts/start.sh` 一键启动；
   - `scripts/accept.py` 端到端验收。

5. **测试**
   - 初版 10 个单元测试；
   - 修复分块测试文本过短、元数据字段遮蔽、嵌入返回值解包等问题；
   - 全部通过。

### 2026-11-01

6. **真实运行**
   - 启动独立 PowerContext 实例（独立数据目录），避免历史数据干扰；
   - 导入 5 篇样例，得到 26 个片段；
   - 在浏览器中验证检索、详情、文献库、记忆页；
   - 截图保存到 `docs/assets/`。

7. **交互优化**
   - 检索结果按论文去重，每篇最多 2 段，避免单篇刷屏；
   - 启动时后台预热 ONNX 模型与语料缓存；
   - 清除偏好时归一化为空对象；
   - 高亮样式改为底部标记，减少误读为删除线；
   - 页脚固定到底部。

8. **样例压缩与最终验收**
   - 演示 PDF 使用 PyMuPDF 做字体子集化，单篇从约 9.4MB 降至 55-70KB，文本逐页比对一致；
   - 清空旧索引后重新导入，仍为 5 篇 / 26 片段；
   - 15 个单元测试通过；
   - 24 项端到端验收全部通过（`2026-11-01T11:32:41`）；
   - 生成 `docs/verification/` 下的报告、直读响应与重启对照。

9. **文档与网站**
   - 编写 README、架构、API、验收、Qoder 记录；
   - 重做 Qoder Sites 项目网站，使用本轮真实运行截图；
   - 通过 prepare action `1071b22a-c44a-4d9e-a580-cdf785f7b5ae` 打包，发布操作 `01a194f7-3006-7bb3-8612-91bdda581481` 完成；
   - 公开地址 `https://paperdesk-4qzym26fsnz.qoder.zone`，首页与静态资源均返回 HTTP 200。

10. **提交**
    - 以仅含 `qoder/.gitkeep` 的上游提交为基线重建分支历史；
    - 保留 gaode / minimax / stepfun 目录，整体替换 `qoder/`；
    - 实现提交 `1131a2714ac648ab57574eacf33197dc51a1236d` 已推送到 `2026-competition-ecosystem`。

11. **记忆读回审计与修复**
    - 发现 PowerContext 的条目库存按 artifact 排列，不是按时间倒序；单页读取会在轨迹增长后漏掉最新偏好；
    - 改为按 `kind` 过滤并沿 `next_cursor` 翻完所有页，再按 `saved_at` 选最新；
    - 新增 `GET /api/preferences?fresh=1`，绕过 12 秒进程缓存；
    - 验收脚本增加“绕过应用直读 PowerContext”和“完全重启后读回”，最终达到 24/24；
    - `seed.py` 与重复上传都会保留原始 PDF，5/5 篇 `/file` 返回 `%PDF`；
    - 启动脚本统一 `POWERCONTEXT_HOME=runtime/powercontext`，并校验 18000 端口属于同一 scope；
    - 站点移除“在线服务”式表述，改为明确的 Qoder Sites 项目介绍页；artifact、导出字节数与截图全部换成最终验收数据。

12. **最终提交与重新发布**
    - 本轮修复提交 `e9b0e5efde77f7b48f3254bd8b519d337405c6dd` 已推送到 `2026-competition-ecosystem`，最终哈希以分支 HEAD 为准；
    - 站点以准备操作 `59de7ede-1971-41d0-9aa2-e98b992fc84d`、发布操作 `01a19533-96f8-763b-8b87-5eb319971f28` 重新发布，状态 `published: true`、`committed: true`、`public`、`active`；
    - 发布后线上首页 HTTP 200，包含 `24 / 24 PASS`、最终 artifact 与新增截图，静态资源均返回 200；
    - 发布后不暂停、不删除站点，评审结束前保持在线。

## 3. 关键问题与处理

| 问题 | 处理 |
| --- | --- |
| seekdb 无法打开含非 ASCII 字符的路径 | 启动时检测并回退到 `%LOCALAPPDATA%\PaperDesk\data-v2` |
| `PaperMeta` 的 `field` 名称遮蔽 `dataclasses.field` | 引入 `dataclass_field` 别名 |
| `resolve()` 返回三元组，旧调用按二元组解包 | 修正解包并返回模型后缀 |
| PowerContext `atomic-memory/list` 条目按 artifact 排列，不是按时间倒序 | 按 `kind` 过滤并翻完所有页，按 `saved_at` 取最新偏好 |
| 单页读取在轨迹增长后漏掉最新偏好 | 新增 `fresh=1` 强制回源，验收再直接查询 PowerContext 比对 artifact |
| 样例 PDF 未复制到上传目录，详情没有“打开 PDF” | `seed.py` 与重复上传都保存 PDF，验收检查 5/5 篇 `%PDF` |
| 手动启动与脚本使用不同 PowerContext 数据目录 | 统一 `POWERCONTEXT_HOME`，并校验 18000 端口 scope |
| 验收结束后清空偏好，评审打开记忆页为空 | 验收先清除再写回最终四条偏好，报告记录 `final_artifact` |
| 清空偏好后仍返回全空字段对象 | 序列化时丢弃空值，清除后读取为 `{}` |
| 同一篇论文占据大量结果位 | 按 `paper_id` 限制每篇 2 段 |
| 首次查询需要加载 ONNX 模型 | 启动后后台预热；文档标注首次查询可能较慢 |
| 移动端截图首查耗时异常 | 预热后重测；常规查询 0.2-0.6 秒 |

## 4. 交付物

| 交付物 | 位置 |
| --- | --- |
| 源代码 | `qoder/backend`、`qoder/frontend` |
| 演示数据 | `qoder/samples`、`qoder/data`（本地生成，不入库） |
| 启动脚本 | `qoder/scripts/start.ps1`、`start.sh` |
| 验收脚本 | `qoder/scripts/accept.py` |
| 测试 | `qoder/tests` |
| 验收记录 | `qoder/docs/verification.md` |
| Qoder 记录 | `qoder/docs/qoder-records.md` |
| 项目网站 | `qoder/site`，已发布到 Qoder Sites |

## 5. 开发边界

- 未使用外部文献数据、未抓取第三方内容；
- 未提交 `.env`、`config/powercontext.env` 或任何密钥；
- 演示 PDF 为原创生成，仅用于验证检索与记忆链路；
- 本次代码、测试、截图与站点内容均在本 Qoder 会话中产生。
