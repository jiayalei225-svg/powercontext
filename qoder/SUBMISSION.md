# PaperDesk 提交说明

## 一、基本信息

| 项 | 内容 |
| --- | --- |
| 项目名称 | PaperDesk · 文献检索工作台 |
| 项目网站 | <https://paperdesk-4qzym26fsnz.qoder.zone>（Qoder Sites，公开访问） |
| 代码仓库 | <https://github.com/jiayalei225-svg/powercontext> |
| 代码目录 | `qoder/`（分支 `2026-competition-ecosystem`） |
| 提交分支 | `2026-competition-ecosystem` |
| Qoder UID | `01a191a9-93d1-776f-b48c-c3727d164e84` |
| 指定技术 | seekdb（混合检索）+ PowerContext（记忆偏好） |
| 运行说明 | 本文件第四节 + `README.md` |
| 验证样例 | `scripts/seed.py` + `scripts/verify.py`（14/14） |

> commit 以仓库 HEAD 为准：`git rev-parse HEAD`。最终提交的 commit hash 见平台提交记录。

## 二、项目解决什么问题

读研/写综述/跟课题时，文献散在多个文件夹，记得“那篇讲 GNN 过平滑的”但记不住标题；
通用搜索返回整篇 PDF，仍要 Ctrl+F 翻页；年份、会议、是否开源这些偏好每次都要重设。

PaperDesk 把 PDF 变成带页码的段落，用 seekdb 做向量 + 全文 + 元数据的库内混合检索，
用 PowerContext 记住检索偏好。命中直接给“第几页的哪一段”，而不是一个文件。

## 三、两个指定技术的分工

| 技术 | 实际作用 | 可核对位置 |
| --- | --- | --- |
| seekdb | 存储段落/向量/元数据；`hybrid_search` 在库内做 RRF 融合与标量过滤 | `backend/app/store.py`、`docs/architecture.md` |
| PowerContext | 保存偏好（preference）与每次检索（progress）；检索前读出并转成 `where` | `backend/app/memory.py`、`backend/app/search.py` |

因果链：同一句 query，写入偏好前后结果集从 12 段收缩到 3 段，且 3 段全部满足约束。
`scripts/verify.py` 会逐项断言并打印 artifact/revision。

## 四、从安装到启动（Windows）

```powershell
cd qoder
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# 另开一个窗口：
.\.venv\Scripts\python.exe scripts\seed.py
# 浏览器打开 http://127.0.0.1:8080
```

macOS / Linux：

```bash
cd qoder
bash scripts/start.sh
.venv/bin/python scripts/seed.py
```

依赖版本固定在 `requirements.txt`：pyseekdb 1.4.0.post1、pylibseekdb 1.4.0.post2、
powercontext[server] 1.4.1、fastapi、uvicorn、PyMuPDF、jieba、httpx。
前端构建产物已提交，评审核验无需安装 Node。

数据目录：seekdb 不能打开非 ASCII 路径。仓库在中文路径下时，程序会自动回退到
`%LOCALAPPDATA%\PaperDesk\data`；也可用 `PAPERDESK_DATA_DIR` 指定纯英文路径。

## 五、验证样例（可按步骤执行）

前置：API 与 PowerContext 已启动，`seed.py` 已导入 4 篇样例（12 段）。

```powershell
.\.venv\Scripts\python.exe scripts\verify.py --reset
```

预期输出（本机实测，完整见 `docs/verification-log.txt`）：

```
== 1. 服务健康 ==
  [PASS] seekdb 可用 — 4 篇 / 12 段
  [PASS] 嵌入模型 — bge-small-zh-v1.5 (local)
  [PASS] PowerContext 已连接 — http://127.0.0.1:8000
== 3. 第一次检索（记忆为空）==
  [PASS] 命中结果 — 12 段
  [PASS] 首条命中《图神经网络》第 2 页
  [PASS] 未应用记忆偏好 — memory_notes 为空
== 4. 写入偏好到 PowerContext ==
  [PASS] 偏好写入成功 — artifact ... rev 1
== 5. 第二次检索（同样的 query，记忆生效）==
  [PASS] 检索时自动应用了偏好 — 3 条
  [PASS] 结果全部满足记忆约束 — 3 段，违规 0 段
  [PASS] 结果数量因过滤而收缩 — 12 → 3 段
== 6. 记忆留痕 ==
  [PASS] 偏好条目存在
  [PASS] 检索记录被写入
== 7. 重启后偏好仍在（跨会话复用）==
  [PASS] 重新读取到同一份偏好
结果：14/14 项通过
```

手工验证同一过程：右侧记忆面板保存偏好 → 中间检索同一句话 → 结果上方黄色提示条
逐条列出“按记忆改了什么”，结果数从 12 变 3。

## 六、Qoder 使用与记录

- 项目网站通过 **Qoder Sites** 创建并发布，访问范围为 public；project/site/release/operation ID
  见 `docs/qoder-sites.md`。
- Qoder 桌面端用于账号与站点归属核对；Qoder CLI 1.1.81 用于读取 Sites 操作目录与发布契约。
- 记录文件：`docs/qoder-records/`（桌面端截图、CLI 输出、发布后站点截图）。
- **边界说明**：代码主体由作者与 AI 结对（DeepSeek Harness）完成，Qoder 的实际作用是
  账号/站点归属、Sites 发布与站点运维记录。这里不把 Qoder 未参与的编码写成 Qoder 的产出；
  开发过程见 `docs/development-log.md`。

## 七、使用效果（自测）

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 验收断言 | 14/14 PASS | `docs/verification-log.txt` |
| 检索中位耗时 | ~115 ms（优化前 ~6.5 s） | 5 条 query 实测，见 `docs/architecture.md` |
| 记忆过滤 | 12 段 → 3 段，违规 0 | `verify.py` |
| 站点访问量 | 2 / 500（Qoder Sites 配额） | `GET /sites/{id}` |

暂无外部真实用户数据；不把自测访问量包装成用户规模。

## 八、材料索引

| 材料 | 位置 |
| --- | --- |
| 项目网站 | <https://paperdesk-4qzym26fsnz.qoder.zone> |
| 代码 | `qoder/backend`、`qoder/frontend`、`qoder/scripts` |
| 运行说明 | `qoder/README.md`、本文件第四节 |
| 验证样例 | `qoder/scripts/verify.py`、`docs/verification-log.txt` |
| 架构说明 | `docs/architecture.md` |
| 开发记录 | `docs/development-log.md` |
| Qoder 记录 | `docs/qoder-sites.md`、`docs/qoder-records/` |
