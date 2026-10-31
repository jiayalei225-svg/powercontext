# 开发记录

## 工具说明（先讲清楚）

| 工具 | 在本项目中的实际作用 |
| --- | --- |
| DeepSeek Harness（AI 结对） | 需求拆解、代码生成与修改、调试、验证脚本执行，占开发工作的大头 |
| Qoder 桌面端 / CLI | Qoder 账号与站点归属、Sites 发布链路的核对（`qoder sites operations` / `describe`） |
| Qoder Sites | 托管并公开发布项目网站 |
| seekdb / PowerContext | 项目的两个核心依赖，见 `docs/architecture.md` |

本记录不把 Qoder 未参与的编码工作算成 Qoder 的产出；Qoder 的站点发布证据单独放在
`docs/qoder-sites.md` 与 `docs/qoder-records/`。

## 时间线

### 1. 需求收敛

真实场景：读研/写综述时，文献散在多个文件夹，记得“那篇讲 GNN 过平滑的”，但记不住标题；
通用搜索返回整篇 PDF，仍要 Ctrl+F 翻页；年份、venue、是否开源这些偏好每次都要重设。

收敛为三个可验收的能力：

1. 页级定位（命中必须带论文、年份、会议、页码、原文片段）；
2. 混合检索（向量 + 关键词 + 元数据过滤，且在库内融合）；
3. 记忆偏好（写入后，同一 query 的结果集必须变化）。

### 2. 数据与接口

- `ingest.py`：PyMuPDF 逐页解析，按约 360 字/60 字重叠切块；论文 ID 用文件内容 SHA-256，
  重复上传返回 409，扫描版无文本 PDF 返回 422。
- `store.py`：一个 `paper_chunks_<embedding>` collection，段落原文 + 向量 + 元数据。
- `search.py`：偏好合并 → `where` → 关键词稀有度选择 → `hybrid_search` → 页级结果。
- `memory.py`：PowerContext `/v1/memory/remember` 与 `/v1/memory/entries/list`，
  偏好/检索日志用带前缀的 JSON 文本存储，读取时挑最新 `saved_at`。

### 3. 界面

React 三栏：左文献库、中检索与结果、右记忆面板。
结果卡片显示标题、年份、venue、页码、高亮片段；记忆面板能编辑偏好并看到 artifact/revision。

### 4. 验证

`scripts/verify.py` 做 7 组 14 项断言，核心因果链是：

- 第一次检索（记忆为空）：命中 12 段，首条是 GNN 笔记第 2 页；
- 写入偏好（2020+ / NeurIPS / 有代码）到 PowerContext，返回 artifact 与 revision；
- 第二次同一 query：自动套用记忆，结果收缩到 3 段，且全部满足约束；
- `/api/memory` 能看到偏好与检索进度条目；
- 重新读取偏好内容一致。

本机结果：**14/14 通过**，完整输出见 `docs/verification-log.txt`。

### 效果数据（截至 2026-10-31，自测）

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 验收断言 | 14/14 PASS | `docs/verification-log.txt` |
| 检索中位耗时 | ~115 ms（优化前 ~6.5 s） | 5 条 query 的实测，见 `docs/architecture.md` |
| 样例规模 | 4 篇 / 12 段 | `/api/health` |
| 记忆过滤效果 | 12 段 → 3 段，违规 0 | `scripts/verify.py` |
| 站点访问量 | 2 / 500（Qoder Sites 配额） | `GET /sites/{id}` 的 `traffic_quota` |

目前没有外部真实用户数据；站点访问量是发布后的自测请求，不包装成“用户规模”。
后续如交给同学试用，会把访问统计导出、问卷结果和改进记录补到 `docs/use-effect/`。

### 5. 调试与修复（真实踩坑）

| 问题 | 现象 | 修复 |
| --- | --- | --- |
| 中文路径 | `seekdb_open failed: code=-1`，服务启动即失败 | `config.py` 检测绝对路径非 ASCII，自动回退到 `%LOCALAPPDATA%\PaperDesk\data` |
| 检索慢 | 每次检索 5–7 s | 定位到每次新建 3 个 PowerContext HTTP 连接（本机建连 ~1.5 s）+ 3 次 `$contains` 探测；改连接池 + 偏好 TTL 缓存 + 语料缓存后 **~115 ms** |
| 关键词噪声 | “神经网络”这类高频词让全文分支失效 | 取 query 实词中语料出现次数最少的一个 |
| 偏好未生效 | 第二次检索结果不变 | `save_preferences` 返回后立即刷新缓存；`search._merge` 只在请求未显式给条件时套用记忆 |

### 6. 发布

- 站点打包为 `qoder-sites.json` + `web/`，按 Qoder Sites deployment → publish 链路发布；
- 公开地址 <https://paperdesk-4qzym26fsnz.qoder.zone>，未登录可访问；
- 发布细节与 ID 见 `docs/qoder-sites.md`。

## 复现

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
.\.venv\Scripts\python.exe scripts\seed.py
.\.venv\Scripts\python.exe scripts\verify.py --reset
```

Linux/macOS 用 `scripts/start.sh`。不要求 Docker、MySQL 或单独部署 seekdb。
