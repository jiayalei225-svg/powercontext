# 基础验收自查表

对照赛题 3.1 的四条基础要求，逐项给出可核对材料。

| 要求 | 本作品如何满足 | 评审怎么核对 |
|---|---|---|
| **能够运行**：DSL 可导入，模型/插件/数据/后端可配置，应用能接收输入并返回结果 | Dify 1.17.0 + DSL `0.3.1`；10 节点 Chatflow；PowerContext 1.4.1 用一条命令启动；模型可换真实模型或本地 shim；无外部数据库/知识库依赖 | 按 [runbook](runbook.md) 导入 DSL、绑定模型、改 `POWERCONTEXT_BASE`，输入 `开始游戏` 应返回选身份界面；`tools/validate_dsl.py` 的 graphon 官方解析为 `loadable` |
| **能够体验主要功能**：至少一组完整验证样例，含初始条件、输入、操作、预期 | [verification.md](verification.md) 给出 5 组样例：demo 续局、跨会话 NPC 记忆、完整预言家局、模型失败兜底、PowerContext 直查 | 按样例 1 用 `seed_demo.py` + `继续` + `投 3`；按样例 2 玩一局后新会话开新局，看「第 1 局」记忆回响 |
| **技术结合有效**：Dify 承担核心流程，PowerContext 实际发挥作用 | Dify 承担输入、3 次 HTTP、规则引擎、LLM、渲染、输出；PowerContext 存每回合完整存档 + 终局 match，驱动跨会话续局、NPC 信任和台词；有 3 个 HTTP 节点的真实请求/响应 | Dify 运行历史看 `scope`/`recall`/`save` 节点；PowerContext API 看 entries；`scripts/verify.py` 断言每回合存档、ended match、跨会话 gid 一致 |
| **过程可以复现**：材料/步骤完整，不依赖作者本地未交付的数据或服务 | 所有代码/DSL/脚本/文档在 `dify/`；模型配置用占位值；PowerContext 数据由 `seed_demo.py` 或首次运行自动生成；无私有知识库/外部数据 | 干净机器按 runbook 从零启动；`seed_demo.py` 生成 demo；`verify.py` 使用随机 `memory_id`，不依赖旧数据 |

## 技术选型说明

- 赛题允许 **seekdb 或 PowerContext 至少一种**。本作品使用 **PowerContext**，未使用 seekdb；
- 没有把 Dify 自带 PostgreSQL 声称为 seekdb；
- PowerContext 使用官方 SQLite 后端，承担真实数据读写，不是“只测连接”。

## 交付物清单

| 赛题要求 | 文件 |
|---|---|
| Dify DSL | `dsl/moonfall-werewolf.chatflow.yml` |
| 运行说明 | `README.md`、`docs/runbook.md` |
| 验证样例 | `docs/verification.md`、`evidence/` |
| 初始化方式 | `scripts/start.ps1` / `start.sh`、`scripts/seed_demo.py` |
| 配套源码 | `engine/`、`tools/`、`scripts/` |
| 自定义插件 | 无（使用 Marketplace 的 OpenAI-API-Compatible） |
| 外部数据 | 无；人物/记忆全部原创 |
| 实际运行证据 | `evidence/logs/verify-report.json`、`evidence/verify-transcript.md` |

## 评分维度对应

| 维度 | 作品中的体现 |
|---|---|
| 创意 | “会记仇的 NPC + 跨会话狼人杀”，记忆不是彩蛋而是胜负变量 |
| 趣味与互动 | 8 人局、身份自由选、NPC 人格、翻旧账、死亡自动收束、月蚀指数 |
| 体验与完成度 | 规则完整、指令清晰、第一夜保护、模型失败兜底、跨会话续局 |
| 技术结合 | Dify 10 节点编排；PowerContext 每回合读写 + 历史关系；无需 seekdb |
| 工程质量 | 引擎单测、DSL 生成器/校验器、轻量执行器、一键验收、完整 runbook |
