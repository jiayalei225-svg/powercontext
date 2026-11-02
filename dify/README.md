# 🌒 月蚀镇 · 会记仇的 AI 狼人杀

> 八个人，两只狼。你是唯一的外乡人。
> 镇上的 NPC 会通过 **PowerContext** 记住你上一局怎么骗他——换个会话、关掉页面再回来，老周仍然记得你欠他一句解释。

**Dify × PowerContext** ｜ 2026 OceanBase × Dify「Just for Fun」参赛作品

---

## 一分钟看懂

你走进月蚀镇，桌上放着八张身份牌。你可以当 **预言家 / 女巫 / 猎人 / 村民 / 狼人**，和七个有自己脾气、秘密和口癖的 NPC 玩一局真正的狼人杀：

- 夜晚：查验、下毒、救人、刀人；
- 白天：自由发言、编故事、带节奏、投票放逐；
- 角色死亡：猎人开枪，其他人则进入「上帝视角」自动收束，保证故事有结尾；
- 第一夜你不会被狼人杀害，先活过第一天才知道谁在说谎。

真正特别的是 **第二局**：

- 上一局你当狼人骗了老周，这一局他开口就是：*“又是你。上次你也这么看着我，结果我是好人。”*
- 上一局你投错了白露，这一局她的信任值更低，发言里会多一根刺；
- 你甚至可以在新会话里直接输入 `继续`，从上一局没打完的夜晚/白天接着玩。

> 这不是「和 AI 聊天」，而是一个有规则、有胜负、有记忆的狼人杀。Dify 负责规则编排与叙事，PowerContext 负责把你的每一局、每个 NPC 的态度存下来。

---

## 为什么值得玩第二局

| 机制 | 玩家感受到什么 | 背后由谁实现 |
|---|---|---|
| **跨会话续局** | 关掉页面、换一个新会话，输入 `继续`，牌局还在原处 | PowerContext 每回合保存完整存档 |
| **NPC 记仇/记恩** | 老周、白露、阿信会翻你上一局的旧账，信任值影响他们的投票与台词 | PowerContext match 记忆 + 引擎关系值 + LLM 提示词 |
| **真狼人杀规则** | 8 人局、2 狼、预言家/女巫/猎人/村民、夜晚行动、投票、屠边式胜负 | Dify Code 节点里的确定性规则引擎 |
| **身份自由选** | 每局可以换身份；狼人、女巫、猎人、村民各有不同的互动方式 | Dify 分支 + 引擎状态机 |
| **NPC 人格** | 七个 NPC 有各自的声线、偏见、秘密；发言不是一排复读机 | Dify LLM 节点 + 人设提示词 + 发言人规划 |
| **不会卡死** | 模型抽风、输出不是 JSON、PowerContext 暂时不可用，流程仍能出完整结果 | 引擎兜底文本 + Render 节点兜底 |
| **死亡也有结尾** | 你出局后，故事会自动收束到胜负揭晓，不会把你晾在聊天框里 | 引擎自动对局 + 终局复盘 |

---

## 技术分工

| 技术 | 承担什么 | 在应用中的实际作用 |
|---|---|---|
| **Dify（必选）** | Chatflow 全流程编排 | 10 个节点：输入登记 → 建 PowerContext Scope → 读记忆 → 规则引擎 → LLM 叙事 → 合并事实 → 写回存档 → 输出 |
| **PowerContext（必选）** | 记忆与对局上下文 | 每个玩家一个 Scope；每回合保存完整 `save` 存档；历史 `match` 提供 NPC 关系、上一局身份/胜负/背叛记录；新会话据此续局与翻旧账 |

> **关于 seekdb**：本题要求 seekdb 或 PowerContext **至少一种**。本作品选择 PowerContext，未使用 seekdb，也不把 Dify 自带的 PostgreSQL 冒充成 seekdb。PowerContext 使用其官方 SQLite 后端，所有记忆读写都有真实 HTTP 记录，见 [`docs/tech-usage.md`](docs/tech-usage.md)。
>
> 三者关系：**Dify 决定“什么时候读/写、怎么用”**；**PowerContext 决定“你是谁、你干过什么、NPC 现在怎么看你”**；**规则引擎决定“这一晚谁死、这一票谁出局”**。

---

## DSL 文件与导入顺序

本作品只需要导入 **一个** DSL 文件：

| 文件 | 用途 | 导入顺序 |
|---|---|---|
| `dsl/moonfall-werewolf.chatflow.yml` | 完整的 Chatflow：输入 → PowerContext 读写 → 规则引擎 → LLM → 输出 | 唯一文件；先启动 PowerContext，再导入 |

- 适用 Dify：**1.17.0**（DSL `0.3.1`）。
- 不需要先导入其他应用、知识库或工具；没有自定义插件包。
- 导入后需要重新绑定 LLM 节点到你自己的模型，并确认环境变量 `POWERCONTEXT_BASE`。
- 重新导入/换模型不会清空 PowerContext 里的玩家记忆。

## 目录结构

```
dify/
├── README.md                          # 本文件
├── requirements.txt                   # Python 依赖（PowerContext + 脚本）
├── dsl/
│   └── moonfall-werewolf.chatflow.yml # 唯一需要导入 Dify 的 DSL
├── engine/
│   ├── moonfall.py                    # 确定性狼人杀引擎（同时嵌入 Dify Code 节点）
│   ├── render.py                      # LLM 输出合并 + 兜底渲染（嵌入 Code 节点）
│   └── tests/                         # 引擎单元测试
├── tools/
│   ├── build_dsl.py                   # 从引擎源码生成 DSL，避免两份逻辑
│   ├── validate_dsl.py                # DSL 结构/变量/JSON/Code/官方 graphon 校验
│   ├── simulate_workflow.py           # 不启动 Dify，按 DSL 节点顺序跑完整局
│   └── openai_shim.py                 # 无模型 Key 时的本地叙事者（可选）
├── scripts/
│   ├── start.ps1 / start.sh           # 一键启动 PowerContext + 本地叙事者
│   ├── stop.ps1 / stop.sh
│   ├── run_powercontext.py            # PowerContext Server 启动器
│   ├── seed_demo.py                   # 预置「已玩两局、第三局进行中」的 demo 档案
│   └── verify.py                      # 一键验收：整局 + 跨会话 + 续局
├── docs/
│   ├── runbook.md                     # 完整运行说明（Dify 部署、导入、模型、网络）
│   ├── verification.md                # 验证样例、预期结果、恢复初始状态
│   ├── tech-usage.md                  # Dify / PowerContext 分工与接口明细
│   ├── architecture.md                # 架构、状态机、记忆 schema
│   └── acceptance-checklist.md        # 基础验收自查表
├── evidence/
│   ├── logs/                          # 实际运行报告
│   └── verify-transcript.md           # 实际对局与跨会话记录
└── data/
    └── README.md                      # 数据来源说明（全部原创）
```

---

## 快速开始

完整步骤（Dify 部署、模型配置、Docker 网络、排错）见 **[`docs/runbook.md`](docs/runbook.md)**。这里是最短路径。

### 1. 启动 PowerContext（和可选的本地叙事者）

Windows：

```powershell
cd dify
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Linux / macOS / WSL：

```bash
cd dify
bash scripts/start.sh
```

看到下面两行即就绪：

```
PowerContext -> http://127.0.0.1:8099
narrator     -> http://127.0.0.1:8101/v1
```

### 2. 写入演示记忆（可选，但强烈建议）

```powershell
.venv\Scripts\python.exe scripts\seed_demo.py
```

它会创建 `memory_id=demo` 的档案：前两局已结束，第三局进行中（你是预言家，第一天，昨晚验了 3 号是狼）。

### 3. 在 Dify 导入 DSL

Dify **1.17.0** → `工作室 → 创建应用 → 导入 DSL` → 选择
[`dsl/moonfall-werewolf.chatflow.yml`](dsl/moonfall-werewolf.chatflow.yml)。

导入后做两件事：

1. **绑定模型**：把「叙事者：月蚀镇的低语」LLM 节点换成你已配置的模型。
   - 推荐：`OpenAI-API-Compatible` 插件 + `deepseek-chat`（或 Qwen / GLM / GPT-4o mini）。
   - 无模型 Key：用本地 shim，Base URL `http://host.docker.internal:8101/v1`，模型 `moonfall-narrator`，Key `sk-local-demo`。
2. **确认服务地址**：DSL 环境变量 `POWERCONTEXT_BASE` 默认 `http://host.docker.internal:8099`。
   - Dify 在 Docker Desktop（Windows/macOS）：保持默认，通常可直接访问宿主机。
   - Linux Docker：给 `api` / `worker` 加 `extra_hosts: ["host.docker.internal:host-gateway"]`，或把它改成宿主机局域网 IP。
   - Dify 源码直跑：改成 `http://127.0.0.1:8099`。

### 4. 开始玩

打开应用，开始表单里：

- **你的称呼**：随便填，留空就是「外乡人」；
- **记忆 ID**：填 `demo` 可直接体验预置记忆；留空则按 Dify 浏览器终端用户隔离。

第一句输入：

- `继续`：接上 demo 第三局（白天，预言家，昨晚验到 3 号是狼）；
- 或 `开始游戏`：带着前两局记忆开新局。

常用指令：

| 场景 | 输入 |
|---|---|
| 选身份 | `预言家` / `女巫` / `猎人` / `村民` / `狼人` / `随机` |
| 预言家查验 | `查 3` |
| 狼人刀人 | `刀 4` |
| 女巫 | `救` / `毒 5` / `不救` |
| 白天发言 | 直接说，例如 `我觉得 2 号在带节奏` |
| 投票 | `投 2` |
| 重开 | `重开确认` |
| 复盘 | `复盘` |

---

## 验证与证据

一键技术验收（需先启动服务）：

```powershell
.venv\Scripts\python.exe scripts\verify.py
```

它会用真实 DSL 跑完一局，再换 `conversation_id` 用同一 `memory_id` 开新局，检查：

- PowerContext Scope 创建、每回合存档、ended match 记忆；
- 新会话是否读到上一局战绩；
- 第二局中途再换会话，是否能续上同一 `gid`；
- LLM 叙事是否被合并进最终回答。

输出：

- [`evidence/logs/verify-report.json`](evidence/logs/verify-report.json)
- [`evidence/verify-transcript.md`](evidence/verify-transcript.md)

离线校验 DSL：

```powershell
.venv\Scripts\python.exe tools\validate_dsl.py
```

完整样例、预期表现与恢复初始状态见 **[`docs/verification.md`](docs/verification.md)**。

---

## 版本与依赖

| 组件 | 版本 | 说明 |
|---|---|---|
| Dify | **1.17.0**（Docker Compose） | DSL 版本 `0.3.1`，向前兼容 Dify 1.x |
| 模型 | `deepseek-chat` / 任意 OpenAI 兼容模型 | 也可用本地 `tools/openai_shim.py` 离线演示 |
| PowerContext | **1.4.1**（`powercontext[server]`，SQLite 后端） | 官方 HTTP API；无需外部数据库 |
| Python | 3.11+（实测 3.13.15 / Windows 11） | 64 位 |
| Dify 插件 | `OpenAI-API-Compatible`（Marketplace） | 若用真实模型；shim 同样走这个插件 |
| seekdb | 未使用 | 本题允许 seekdb 或 PowerContext 二选一 |

---

## 已知限制

- **单机叙事型狼人杀**：AI 玩家的投票是启发式 + 少量随机，不是人类级博弈；重点在沉浸感、记忆和可复现。
- **模型质量决定台词质量**：小模型可能输出不合格 JSON；此时 Render 节点会使用引擎的完整兜底文本，事实和流程不受影响，但文采会下降。
- **PowerContext 列表上限 100 条**：每回合一份存档，演示 8–10 局后建议换 `memory_id` 或重置数据目录（见 verification 文档）。
- **PowerContext 无鉴权**：默认只适合本机/内网演示，不要直接暴露到公网。
- **第一夜主角保护**：这是为了让评审先体验完整流程的设计选择，不是标准狼人杀规则。
- **Dify 网络**：Docker 内访问宿主机需要 `host.docker.internal` 或局域网 IP；Linux 需 `extra_hosts`。

---

## 许可与致谢

- 游戏规则、七个人物、全部提示词、引擎代码、种子记忆均为本作品原创。
- 使用 [Dify](https://github.com/langgenius/dify)、[PowerContext](https://github.com/oceanbase/powercontext) 的开源能力，遵循其各自许可证。
- 没有复用公开工作流的 DSL 或第三方数据集；`tools/openai_shim.py` 仅为本作品离线演示而写。
