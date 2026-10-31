# Edge Atlas 技术说明（一页）

**赛题** 阶跃星辰 · 端侧 AI 推理性能优化与 seekdb 混合检索　**作品** 浏览器端本地向量化 + seekdb 混合检索迷你知识库

## 1. 模型与量化

- 模型：`BAAI/bge-small-zh-v1.5`（4 层 BERT，hidden 512，max 512 token，MIT），ONNX 版 `Xenova/bge-small-zh-v1.5` @ `75c43b069aac4d136ba6bc1122f995fedcfd2781`。CLS pooling + L2 normalize；查询侧使用官方中文检索 instruction，文档侧不加。
- 量化：ONNX Runtime dynamic quantization，weight-only、QUInt8、per-channel；另提供 FP16 模型。独立复现的 INT8 ONNX 为 24,020,718 B，与提交 artifact 相差 0.041%，合成输入 CLS cosine 0.9978。
- 体积（ONNX + tokenizer/config bundle）：FP32 90.88 MiB；FP16 45.72 MiB（1.99×）；INT8 23.32 MiB（3.90×）。
- 质量（20 条查询，seekdb hybrid RRF，topK=5）：FP32 Recall@5 / nDCG@5 = **0.950 / 0.884**；INT8 = **0.950 / 0.878**（nDCG −0.69%，MRR −1.40%）；FP16 与 FP32 排名一致。

## 2. 端侧运行：WebGPU 优先，WASM 自动降级

- 运行时：Transformers.js 4.3.2 + ONNX Runtime Web，全部在 Dedicated Worker 中执行；模型与 ORT wasm 由同源静态目录加载，`allowRemoteModels=false`。
- 启动时探测 `navigator.gpu` 与 `requestAdapter()`：成功则 `device=webgpu, dtype=fp16`；失败（无 `navigator.gpu`、adapter 为 null、WebGPU 会话初始化错误）则自动重建 `device=wasm` 会话，并在 Header/Inspector 显示实际后端、精度、device 与降级原因。
- 若已有 collection 使用 FP16 建立，WASM 降级会保留 FP16 精度，避免 query/index 跨精度不一致；WASM 使用 4 threads（COOP/COEP 已开启）。
- 实测无 GPU 时：HUD 显示 `WASM / FP16`，Inspector 给出 `requestAdapter() 返回空适配器`；检索流程正常，见 `docs/screenshots/wasm-fallback.png`。

## 3. seekdb 存储与混合检索

- 每个知识库独立 collection：`HNSW(dim=512, cosine, M=16, ef_construction=200, ef_search=100)` + IK smart 全文索引；collection 的 `embeddingFunction=null`，向量只来自浏览器。
- 块保存 `documents`（原文）、`embeddings`、`metadata`（docId/title/chunkIndex/charStart/precision…）；注册表保存知识库标题、文档数、块数、最近导入时间。
- 检索调用 `collection.hybridSearch({query:{whereDocument:{$contains:...}}, knn:{queryEmbeddings:[...]}, rank:{rrf:{rankWindowSize:40, rankConstant:60}}})`；向量与全文两路召回、过滤、RRF 融合都在 seekdb `DBMS_HYBRID_SEARCH` 内完成，客户端只做 docId 聚合。
- 增量导入按 16 块/批 `add`，同 docId 先删旧块；完成后 `refresh_index()`，再用新块自身向量做 topK 自查询，确认可检索；失败重试并清理，注册表同步更新。

## 4. 性能与工程优化

| 配置 | Bundle | 文档向量化 54 块 | batch16 吞吐 | 查询编码 p50 | seekdb 检索 p50 | 端到端 p50 | Recall@5 | nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| FP32 · WASM 基线 | 90.88 MiB | 24.32 s | 1.91 texts/s | 78.8 ms | 72.5 ms | 150.1 ms | 0.950 | 0.884 |
| INT8 · WASM | 23.32 MiB | 23.76 s | 2.26 texts/s | 78.5 ms | 103.5 ms | 185.1 ms | 0.950 | 0.878 |
| FP16 · WebGPU | 45.72 MiB | 5.97 s | **70.89 texts/s** | 78.6 ms | 112.2 ms | 190.9 ms | 0.950 | 0.884 |

- WebGPU + FP16 的 batch 16 吞吐约为 WASM 的 31×，证明“把文档批处理放到 GPU”是本题最有价值的端侧优化；batch 32 反而回落到 49.8 texts/s，故 UI 默认 batch=16。
- INT8 的收益主要是体积和加载，不是本机 ORT Web WASM 的单条吞吐；报告保留这一事实，不用“更小”代替“更快”。
- 冷/热初始化（同会话重载）：WebGPU FP16 20.92 s → 17.91 s；ONNX 以 no-store 提供以规避 Chromium 大 body 的 `ERR_CACHE_WRITE_FAILURE`，热启动收益来自连接/浏览器内部缓存，数据已单独留存。
- 计时边界：查询编码从 Worker postMessage 开始；seekdb 检索为 `POST /search` HTTP 往返；端到端到一次 React 渲染；文档向量化为 54 块的实测值。原始 JSON/CSV 与逐条质量在 `docs/benchmarks/`。

## 5. 复现

`npm install` → `npm run setup:model` → `docker compose up -d seekdb` → `npm run build && npm start`；示例语料与 20 条 qrels 随仓库提供；`npm run benchmark`、`npm run smoke`、`npm run test:fallback`、`npm run test:collection` 分别复现上表、完整流程、降级与集合隔离。完整说明见仓库 `README.md`。
