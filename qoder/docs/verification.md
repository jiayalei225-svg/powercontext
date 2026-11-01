# 验收记录

验收时间：2026-11-01 10:14（本地时区）
验收环境：Windows 11，Python 3.x，PowerContext 1.4.1，seekdb 1.4.0，本地 BGE `bge-small-zh-v1.5` 512 维
服务地址：`http://127.0.0.1:18081`（本机 8080 被占用，用 `PAPERDESK_PORT` 覆盖；默认端口仍为 8080）

## 结论

| 项目 | 结果 |
| --- | --- |
| 单元测试 | **11 passed** |
| 端到端验收 | **19 / 19 PASS** |
| 论文入库 | 5 篇 / 26 个片段 |
| 混合检索 | 命中 6 个片段，`strategy=hybrid` |
| 记忆偏好 | 保存、自动应用、显式覆盖、清除均通过 |
| 导出 | Markdown 4.7 KB / CSV 3.9 KB |
| PowerContext | 已连接，检索轨迹正常写入 |

原始报告：

- [report.json](verification/report.json)
- [search.json](verification/search.json)：一次真实检索的完整响应
- [preferences-search.json](verification/preferences-search.json)：应用记忆偏好后的完整响应
- [report.md](verification/report.md) / [report.csv](verification/report.csv)：导出的检索报告

## 单元测试

```text
$ python -m pytest
...........
11 passed
```

覆盖内容：

1. 句读感知分块与页码保留；
2. PDF 头部元数据解析；
3. 文件名回退；
4. seekdb 标量过滤条件组合；
5. 记忆偏好合并；
6. 显式条件覆盖记忆；
7. 每篇论文片段数上限；
8. 片段摘要围绕查询词；
9. Markdown / CSV 导出；
10. 演示 PDF 可读；
11. seekdb 写入、混合检索、过滤、删除往返。

## 端到端验收

执行：

```bash
python scripts/accept.py --base http://127.0.0.1:18081
```

| # | 检查 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 服务健康 | PASS | version=2.0.0，collection=`paper_chunks_v2_bge_zh` |
| 2 | PowerContext 连接 | PASS | scope 可用 |
| 3-7 | 导入 5 篇 PDF | PASS | 每篇 5-6 个片段；重复导入返回 `duplicate=true` |
| 8 | 文献库数量 | PASS | 5 篇 |
| 9 | 论文详情 | PASS | 返回 5 个片段 |
| 10 | 混合检索召回 | PASS | 命中 6，`strategy=hybrid`，1459 ms（重启后首次查询，含模型预热） |
| 11 | 搜索写入记忆 | PASS | `memory_connected=true` |
| 12 | 保存记忆偏好 | PASS | `artifact=art_fa6439…`，`revision=1` |
| 13 | 记忆偏好自动应用 | PASS | 4 个字段生效，`notes=4`，`hits=2` |
| 14 | 显式条件覆盖记忆 | PASS | SIGIR/2023/信息检索/无代码 生效，`applied={}` |
| 15 | 清除记忆偏好 | PASS | 读取为 `{}` |
| 16 | 导出 Markdown | PASS | 4767 字节，以 `# PaperDesk 检索报告` 开头 |
| 17 | 导出 CSV | PASS | 3982 字节，带 UTF-8 BOM |
| 18 | 检索轨迹 | PASS | 12 条 |
| 19 | 记忆快照 | PASS | scope + 20 条轨迹 |

## 关键样例

### 1. 混合检索

查询：`向量数据库里怎么做混合检索`

![检索结果](assets/results.png)

- 词项：检索 / 向量 / 数据库 / 混合
- 字面锚点：数据库
- 策略：向量 + 全文混合召回
- 结果：10 个段落，首篇为《面向向量数据库的混合检索自适应融合方法》，计算机学报 2024
- 上图这次界面查询耗时 240 ms；验收脚本使用 `limit=6` 命中 6 段，界面默认 `limit=12` 展示前 10 段
- 服务空转后的首次查询通常需要 2-5 秒加载 ONNX 模型

### 2. 原文定位

点击标题打开论文抽屉，可直接看到页码、片段序号与完整原文：

![论文详情](assets/drawer.png)

### 3. 记忆偏好

在记忆页保存“2024 年以后 / ACL / 检索增强生成 / 仅开源”，下一次不填写条件直接检索：

![记忆偏好](assets/memory-prefs.png)

检索计划明确标注四条“记忆偏好”，结果全部满足条件：

![记忆生效](assets/memory-applied.png)

保存偏好时返回 artifact ID 与 revision，说明偏好确实以版本化条目写入 PowerContext；清除后重新读取为 `{}`。

### 4. 文献库与移动端

| 文献库 | 移动端 |
| --- | --- |
| ![文献库](assets/library.png) | ![移动端](assets/mobile-results.png) |

## 复现步骤

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
python scripts\accept.py --base http://127.0.0.1:8080
```

如果使用默认端口，期望输出末尾为：

```text
共 19 项，通过 19，失败 0
```

## 说明

- 验收使用 `samples/` 下的 5 篇原创示例 PDF，不依赖外部网络与第三方文献；PDF 已做字体子集化，文本内容与分块结果不变。
- `scripts/accept.py` 会真实上传、检索、写记忆、导出并清理偏好，不是 mock。
- 报告中的 artifact 与 revision 来自 PowerContext 真实响应；每次运行会生成新的 artifact。
- 截图来自本机实际运行界面，由本 Qoder 会话内的无头浏览器与桌面窗口捕获生成。
