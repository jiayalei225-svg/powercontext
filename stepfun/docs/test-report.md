# 测试与技术记录

本文档记录提交应用的实际运行测试、原始数据位置与判定依据。所有测试均通过提交的页面执行，不存在服务端预计算向量或客户端假检索。

## 1. 环境

| 项目 | 值 |
| --- | --- |
| 设备 | ASUS FA608PM / AMD Ryzen 9 8940HX（16C/32T）/ 16GB RAM |
| GPU | NVIDIA GeForce RTX 5060 Laptop；WebGPU adapter 报告 `nvidia · blackwell`（另一轮为 AMD `rdna-2`） |
| OS | Windows 11 家庭中文版 10.0.26200 |
| 浏览器 | Microsoft Edge 156.0.0.0（Playwright headless，Chromium 156） |
| 推理 | Transformers.js 4.3.2 / ONNX Runtime Web 1.31.0-dev（随 Transformers.js） |
| 模型 | `Xenova/bge-small-zh-v1.5` @ `75c43b069aac4d136ba6bc1122f995fedcfd2781`（上游 `BAAI/bge-small-zh-v1.5`） |
| seekdb | 1.4.0.0 server 模式，端口 2881（基准测试使用同版本全新实例端口 2883） |
| 语料 | 27 篇中文技术卡片 / 54 个块（400 token 预算、60 overlap） |
| 测试查询 | 20 条中文查询，文档级二值 qrels，topK=5 |

## 2. 测试入口

```bash
npm install
npm run setup:model
docker compose up -d seekdb
npm run build && npm start

npm run smoke            # 端到端导入 + 检索
npm run test:fallback    # 无 WebGPU 自动降级
npm run test:collection  # 新建、增量导入、切换隔离、删除
npm run benchmark        # Lab 完整质量/性能
node benchmark/cold-warm.mjs
```

自动化脚本使用 Edge 的 `--force_high_performance_gpu` 选择 RTX 5060；降级测试使用 `--disable-gpu --disable-software-rasterizer`。

## 3. 功能测试

### 3.1 端到端 smoke

结果：27 篇文档、54 个块；`导入完成` 中显示：

| 阶段 | 本次耗时 |
| --- | ---: |
| tokenize + 切分 | 33 ms |
| 浏览器本地向量化（54 块） | 4.09 s |
| seekdb 写入 + refresh_index + 自查询 | 2.02 s |
| HTTP 往返 | 2.06 s |
| 自查询验证 | 通过 |

随后查询 `seekdb 如何把关键词和语义两路结果融合排序？`，页面显示 8 篇文档（从 32 个 chunk 聚合），第一页结果为 seekdb 混合检索相关文档；查询编码 73 ms、seekdb 65 ms、端到端 184 ms。

截图：[atlas-results.png](screenshots/atlas-results.png)

### 3.2 WebGPU 不可用时的自动降级

启动参数禁用 GPU 后，浏览器中 `navigator.gpu` 仍存在，但 `requestAdapter()` 返回 `null`。应用：

- 自动回退到 WASM；
- 保留已有 collection 的 FP16 精度，避免跨精度查询；
- Header 显示 `WASM / FP16`；
- Inspector 显示 `navigator.gpu 存在，但 requestAdapter() 返回空适配器`；
- 检索流程继续返回结果。

截图：[wasm-fallback.png](screenshots/wasm-fallback.png)
原始记录：[fallback-run.json](benchmarks/fallback-run.json)

### 3.3 新建知识库、切换与隔离

自动化脚本执行：

1. 新建 `潮汐能隔离测试` collection；
2. 在空知识库中粘贴 1 篇「潮汐发电原理」，本地向量化并写入；
3. 查询「潮汐电站如何利用水位差发电？」，首条结果为「潮汐发电原理」；
4. 切回 `端侧检索 · Edge Atlas`，同一查询不含潮汐文档；
5. 删除测试 collection，剩余 collection 数 = 1。

全部通过，说明 collection 切换与文档级隔离正确。

## 4. 量化与质量

### 4.1 量化

- 方案：ONNX Runtime `quantize_dynamic`，weight-only、QUInt8、per-channel。
- 复现脚本：`python scripts/quantize_model.py`。
- 复现结果：24,020,718 B（22.91 MiB），相对 FP32 ONNX 压缩 3.949×。
- 提交使用官方 artifact：24,010,842 B（22.90 MiB），与复现件相差 +0.041%。
- 合成输入（2 个随机 token batch）CLS 向量 cosine：0.9978。

完整日志：[quantization.txt](benchmarks/quantization.txt)

### 4.2 质量指标

- Recall@5：前 5 篇文档覆盖的相关文档数 / 该 query 的相关文档总数。
- nDCG@5：二值相关性，折损 `1/log2(rank+1)`，除以理想 DCG。
- MRR@5：第一个相关文档名次的倒数，5 名外为 0。
- 文档级去重：同一 docId 多个块只保留最高分结果；此聚合在 seekdb 返回之后进行，不改变数据库检索。

| 配置 | Recall@5 | nDCG@5 | MRR@5 |
| --- | ---: | ---: | ---: |
| FP32 · WASM 基线 | 0.950 | 0.8841 | 0.8917 |
| INT8 · WASM | 0.950 | 0.8779 | 0.8792 |
| FP16 · WebGPU | 0.950 | 0.8841 | 0.8917 |

INT8 相对 FP32：Recall 不变，nDCG −0.69%，MRR −1.40%。20 条查询中有 18 条完全命中，未命中的是：

- Q01「浏览器不支持 WebGPU…」：`web-worker` 排在 `webgpu-wasm` 前，qrels 认为 `onnx-runtime-web` 也相关；
- Q16「batch size 越大吞吐越高吗」：`batching` 命中，但 `benchmark-method` 未进入前 5。

这两条属于语料中多篇文档语义相近导致的排序差异，不是检索失败（页面仍返回相关文档）。

### 4.3 三路检索对比（FP32）

| 模式 | Recall@5 | nDCG@5 | MRR@5 |
| --- | ---: | ---: | ---: |
| Hybrid RRF | 0.950 | 0.884 | 0.892 |
| Vector only | 0.925 | 0.819 | 0.800 |
| Fulltext only | 0.975 | 0.871 | 0.850 |

混合检索相对纯向量：Recall +2.5 pp、nDCG +6.5 pp、MRR +9.2 pp；相对纯全文，Recall 略低但 nDCG/MRR 更高。三种模式的全部检索均由 seekdb 执行。

## 5. 性能

完整原始 JSON：[benchmark-final.json](benchmarks/benchmark-final.json) · CSV：[benchmark-final.csv](benchmarks/benchmark-final.csv)

测试由页面内的「Lab」调用同一套 Worker、API、seekdb collection 和查询集。每个配置临时创建 collection，导入 54 块，执行 20 条 query、三种模式，再做 batch 扫描，完成后自动删除 collection 并恢复原引擎。

| 配置 | Bundle | 模型初始化 | 54 块向量化 | batch16 吞吐 | query embed p50 | seekdb p50 | e2e p50 | e2e p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 · WASM | 90.88 MiB | 7.29 s | 24.32 s | 1.91 texts/s | 78.8 ms | 72.5 ms | 150.1 ms | 178.5 ms |
| INT8 · WASM | 23.32 MiB | 9.80 s | 23.76 s | 2.26 texts/s | 78.5 ms | 103.5 ms | 185.1 ms | 217.9 ms |
| FP16 · WebGPU | 45.72 MiB | 14.40 s | 5.97 s | **70.89 texts/s** | 78.6 ms | 112.2 ms | 190.9 ms | 251.9 ms |

Batch 扫描（36 个固定块、两轮中位数）：

| 配置 | b1 | b8 | b16 | b32 |
| --- | ---: | ---: | ---: | ---: |
| FP32 · WASM | 2.00/s | 1.86/s | 1.91/s | 1.83/s |
| INT8 · WASM | 3.12/s | 2.22/s | 2.26/s | 3.00/s |
| FP16 · WebGPU | 13.19/s | 53.01/s | **70.89/s** | 49.75/s |

冷/热启动（同浏览器会话，WebGPU FP16）：[cold-warm.json](benchmarks/cold-warm.json)

| 项目 | 值 |
| --- | ---: |
| 冷启动页面到模型就绪 | 20.92 s（导航到就绪 27.40 s） |
| 同会话重载后模型初始化 | 17.91 s（导航到就绪 20.84 s） |
| 冷/热差异 | −14.4% |

> ONNX 以 `Cache-Control: no-store` 提供，规避 Chromium 对 24–95 MiB body 偶发的 `net::ERR_CACHE_WRITE_FAILURE`。因此热启动数字更保守，主要是连接复用与浏览器内部缓存；这与 HTTP 磁盘缓存不同，报告中已区分。

### 5.1 指标解释

- `模型初始化` 是 Worker 内 pipeline 加载到 ready 的 `loadMs`，包含 tokenizer 与 ONNX session/GPU compile；不等于网络下载时间。
- `54 块向量化` 是导入流程中的一次真实批量 embedding，包含 tokenizer 与 padding，不等于 batch 扫描的短文本吞吐。
- batch 扫描固定 36 个 400-token 文本块，先 warmup 再每档两轮；只改变 batch size。
- `query embed p50` 是 20 条 query 的单条编码耗时中位数。
- `seekdb p50` 是 `POST /api/kbs/:id/search` 的 HTTP 往返，包含 DB 检索与 JSON 序列化。
- `e2e p50` 从点击检索到结果状态可渲染，不含截图或测试框架开销。
- 写入/refresh 时间受 seekdb 后台 compaction 影响明显（本次完整运行中三个配置分别为 4.33 s / 5.86 s / 57.04 s 长尾），故不作为主表列；功能验证中的一次完整示例导入为 2.02 s server 侧写入+refresh。建议复现时在空实例上重复测。

## 6. 已知环境噪声

这台笔记本同时运行着其他开发进程（Trae、飞书、WSL 中的 Docker/构建任务等），seekdb 写入与查询在不同轮次有 2–10× 的噪声。相同代码、相同语料曾测到 70 ms 级 seekdb 查询和 169 ms 端到端（见 smoke 记录），也测到 1.3 s 的 DB 查询。基准表和原始 JSON 保留同一次运行的数据，不挑选单个最快值；绝对延迟以实际设备为准。

## 7. 提交材料对照

| 要求 | 位置 |
| --- | --- |
| 可运行应用 | `server/` + `src/` + `README.md` 启动步骤 |
| 完整源码 | 本目录；模型通过 `scripts/download-model.mjs` 固定 revision 下载 |
| 一页技术说明 | `docs/technical-report.md` / `docs/technical-report.pdf` |
| 集合/表结构、索引配置 | `server/seekdb-service.mjs`，本文 §4 + README §4 |
| 复现数据/生成方式 | `data/sample-corpus.json`、`data/eval/queries.json`、`scripts/` |
| 原始测试数据 | `docs/benchmarks/*.json`、`*.csv`、`*.txt` |
| 降级证据 | `docs/screenshots/wasm-fallback.png`、`benchmark/fallback-test.mjs` |
| 质量对比 | `docs/benchmarks/benchmark-final.json` 的 `quality` 字段 |
