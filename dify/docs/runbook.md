# 运行说明（Runbook）

本文从一台干净的机器开始，说明如何把《月蚀镇》跑起来。最短路径见项目 [README](../README.md)。

---

## 0. 作品与体验方式

- **作品**：一个 8 人局、单机叙事型 AI 狼人杀。玩家是第 8 个人，另外 7 个是有性格、有秘密、会记仇的 NPC。
- **核心玩法**：选身份 → 夜晚行动 → 白天发言/投票 → 胜负揭晓。玩家可以当预言家、女巫、猎人、村民或狼人。
- **技术结合**：Dify 负责核心流程；PowerContext 保存每回合存档、历史战绩和 NPC 关系。换一个会话输入 `继续` 可以续局；开新局时 NPC 会引用上一局。
- **入口**：Dify Chatflow 的应用界面（或 Dify API），无需独立前端。

---

## 1. 运行环境与版本

| 组件 | 版本 / 要求 | 说明 |
|---|---|---|
| Dify | **1.17.0**，Docker Compose 部署 | DSL 版本 `0.3.1`；Dify 1.x 均可尝试 |
| Dify 插件 | `OpenAI-API-Compatible`（Marketplace） | 用于 DeepSeek / Qwen / OpenAI / 本地 shim |
| 模型 | `deepseek-chat` 或任意 OpenAI 兼容 chat 模型 | 中文能力越好，台词越好 |
| PowerContext | **1.4.1**，`powercontext[server]`，SQLite 后端 | 官方 HTTP API；无需外部数据库 |
| Python | **3.11+**（实测 3.13.15，Windows 11 64 位） | 用于启动 PowerContext 和脚本 |
| 端口 | `8099`（PowerContext）、`8101`（本地 shim） | 可改，DSL 环境变量同步改 |
| 资源 | Dify 建议 4 GB 内存；PowerContext < 200 MB | 首次装依赖需要网络 |

> 本作品**未使用 seekdb**。题目允许 seekdb 或 PowerContext 二选一；所有记忆能力由 PowerContext 承担，详见 [tech-usage](tech-usage.md)。

---

## 2. 启动 PowerContext（和可选的本地叙事者）

### 2.1 Windows 一键

```powershell
cd dify
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

首次会创建 `.venv` 并安装依赖（约 1–3 分钟）。脚本会：

- 启动 PowerContext：`http://127.0.0.1:8099`，监听 `0.0.0.0` 以便 Dify Docker 访问；
- 启动本地叙事者 shim：`http://127.0.0.1:8101/v1`；
- 把 PID 写入 `logs/pids.json`。

看到以下输出即成功：

```
PowerContext -> http://127.0.0.1:8099
narrator     -> http://127.0.0.1:8101/v1 (model=moonfall-narrator)
data dir     -> C:\Users\<you>\AppData\Local\Moonfall\powercontext
```

### 2.2 Linux / macOS / WSL 一键

```bash
cd dify
bash scripts/start.sh
```

### 2.3 手动启动（排错时使用）

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\run_powercontext.py --host 0.0.0.0 --port 8099
# 另一个终端
.venv\Scripts\python.exe tools\openai_shim.py --port 8101
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8099/health/ready -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8101/health -UseBasicParsing
```

### 2.4 数据位置与重置

- 默认：Windows `%LOCALAPPDATA%\Moonfall\powercontext\`；Linux `~/.local/share/moonfall/powercontext/`。
- 重置：先 `scripts\stop.ps1`（或 `stop.sh`），删除上述目录，再启动。会清空所有玩家记忆。
- 只想换一个演示档案：`seed_demo.py --memory-id demo2`，不需要删数据。

---

## 3. 部署 Dify 1.17.0

如果已有 Dify 1.17.0，可跳过本节。

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

打开 `http://localhost`（或 `.env` 中的 `EXPOSE_NGINX_PORT`），完成管理员初始化。

> 如果 Dify 已经跑在其他机器/容器，只需要保证 Dify 的 `api` 和 `worker` 容器能访问 PowerContext 的 8099 端口。

---

## 4. 配置模型

### 4.1 安装插件

Dify 控制台 → **插件 / Plugins** → Marketplace → 安装 **OpenAI-API-Compatible**。

### 4.2 方案 A：真实模型（推荐）

设置 → 模型供应商 → OpenAI-API-Compatible → 添加模型：

| 字段 | 示例（DeepSeek） |
|---|---|
| Base URL | `https://api.deepseek.com/v1` |
| API Key | 你的 Key（不要提交到仓库） |
| Model Name | `deepseek-chat` |
| Context Size | `64000`（按供应商填） |
| Max Tokens | `4096` |

也可以用 Qwen、GLM、Moonshot、OpenAI 等任意 OpenAI 兼容服务。

### 4.3 方案 B：本地 shim（无 Key，离线演示）

| 字段 | 值 |
|---|---|
| Base URL | `http://host.docker.internal:8101/v1` |
| API Key | `sk-local-demo`（占位，不校验） |
| Model Name | `moonfall-narrator` |
| Context Size | `8192` |
| Max Tokens | `2048` |

Linux Docker 如果 `host.docker.internal` 不通，见第 6 节。

> shim 只生成模板台词，不会像真实模型那样即兴创作；它的价值是让评审在没有 Key 时也能完整跑通。正式体验请用真实模型。

---

## 5. 导入 DSL 与配置

### 5.1 导入

Dify → 工作室 → 创建应用 → **导入 DSL 文件** → 选择：

```
dify/dsl/moonfall-werewolf.chatflow.yml
```

导入后应用名为「月蚀镇 · 会记仇的 AI 狼人杀」，类型 Chatflow。

### 5.2 绑定模型

打开应用 → 编排 → 点击 **「叙事者：月蚀镇的低语」** LLM 节点：

- 模型：选择你在第 4 节配置的 `deepseek-chat` 或 `moonfall-narrator`；
- 其他参数保持默认（temperature 0.9，max_tokens 1200）；
- 保存。

DSL 里默认写的是 `langgenius/openai_api_compatible/openai_api_compatible` + `deepseek-chat`；如果导入后模型显示未配置，重新选一次即可。

### 5.3 确认 PowerContext 地址

应用 → 编排 → 右上角 **环境变量**：

```
POWERCONTEXT_BASE = http://host.docker.internal:8099
```

按部署方式修改：

| Dify 部署 | 值 |
|---|---|
| Docker Desktop（Windows/macOS） | `http://host.docker.internal:8099` |
| Linux Docker Compose | `http://host.docker.internal:8099` + `extra_hosts`，或 `http://<宿主机局域网IP>:8099` |
| Dify 源码直跑 | `http://127.0.0.1:8099` |
| Dify 在另一台机器 | `http://<PowerContext 所在机器IP>:8099` |

### 5.4 发布应用

点击右上角 **发布** → **运行**。

---

## 6. Docker 网络（Linux / 远程）

`host.docker.internal` 在 Docker Desktop 上默认可用；Linux 需要在 Dify 的 `docker-compose.yaml` 里给 `api` 和 `worker` 加：

```yaml
services:
  api:
    extra_hosts:
      - "host.docker.internal:host-gateway"
  worker:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

然后：

```bash
docker compose up -d
```

如果仍然不通：

1. 在 Dify 的 api 容器里执行 `curl http://host.docker.internal:8099/health/ready`；
2. 检查宿主机防火墙是否放行 8099；
3. 把 `POWERCONTEXT_BASE` 改成宿主机局域网 IP（`ipconfig` / `ip addr`）；
4. 确认 PowerContext 监听 `0.0.0.0`（`start.ps1` 默认如此）。

---

## 7. 初始化演示记忆（推荐）

```powershell
.venv\Scripts\python.exe scripts\seed_demo.py
```

输出会给出 `scope_id`、`memory_id=demo` 和 `entries` 数量。它写入：

- 第 1 局：你当狼人，狼人胜；你骗了老周、阿信；
- 第 2 局：你当预言家，狼人胜；你投错了白露；
- 第 3 局：进行中，你是预言家，第一天，昨晚验了 3 号是狼。

在 Dify 开始表单里：

- 你的称呼：`演示玩家`
- 记忆 ID：`demo`

第一句输入 `继续`，应直接看到「第 1 天」、你的查验记录「3 号 → 狼人」和记忆回响。输入 `投 3` 可以继续玩。

如果之前已经 seed 过，脚本会跳过；要重新生成，见 2.4 节。

---

## 8. 开始体验

### 8.1 新玩家

开始表单留空，直接输入：

```
开始游戏
```

按提示选身份。第一夜不会被狼人杀害。

### 8.2 常用指令

| 场景 | 输入 |
|---|---|
| 选身份 | `预言家` / `女巫` / `猎人` / `村民` / `狼人` / `随机` |
| 预言家查验 | `查 3` |
| 狼人刀人 | `刀 4` |
| 女巫 | `救` / `毒 5` / `不救` |
| 白天发言 | 直接说话，如 `我觉得 2 号在带节奏` |
| 投票 | `投 2` |
| 重开 | `重开确认` |
| 复盘 | `复盘` |

### 8.3 验证样例

见 [verification.md](verification.md)。至少跑一遍：

1. `seed_demo.py` → `继续` → `投 3`；
2. 完整玩一局 → 新会话输入 `开始游戏`，检查是否出现「第 1 局」记忆；
3. 第二局中途换新会话，输入 `开始游戏`，检查是否续上同一局。

---

## 9. 运行验收脚本

```powershell
.venv\Scripts\python.exe tools\validate_dsl.py
.venv\Scripts\python.exe scripts\verify.py
```

- `validate_dsl.py`：结构、变量、HTTP JSON、Code 节点、Dify graphon 官方解析；
- `verify.py`：真实 DSL 跑完一局 + 跨会话记忆 + 中途续局，输出 `evidence/`。

普通运行只需要 `requirements.txt`。如果要复现 136 项（含 graphon 官方解析）校验：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

如果 `verify.py` 没有检测到 8101 的 shim，会自动尝试启动；也可手动先运行 `start.ps1`。

---

## 10. 资源、网络与安全

- **网络**：Dify → PowerContext（8099）必须通；Dify → 模型服务必须通；本地 shim 可选。
- **端口冲突**：8099/8101 被占用时，改 `start.ps1` 参数和 DSL 环境变量；`scripts/run_powercontext.py --port` 可改。
- **安全**：PowerContext 默认无鉴权且监听 `0.0.0.0`，只适合本机/内网演示；不要映射到公网。生产化应加反向代理、鉴权和 TLS。
- **数据**：PowerContext 的 SQLite 文件包含玩家称呼、对局记录；分享前可删除。
- **模型 Key**：DSL、脚本、文档中都没有真实 Key；请只在自己的 Dify 控制台配置。

---

## 11. 常见问题

| 现象 | 排查 |
|---|---|
| `Connection refused` / 节点 500 | PowerContext 没启动；`http://127.0.0.1:8099/health/ready` 是否 200 |
| HTTP 节点返回 422 | Scope 未创建，`prep_scope.scope_id` 为空；查看 scope 节点的响应体 |
| 应用能聊但没记忆 | `POWERCONTEXT_BASE` 不对，或 scope 创建失败；查看 Dify 运行历史里 scope/recall/save 三个节点 |
| 新会话不记得上一局 | 开始表单的「记忆 ID」是否一致；scope key = `moonfall:user:<memory_id 或 sys.user_id>` |
| 输入 `继续` 没反应 | 没有 active 存档时会进入新局；先 `开始游戏`，或跑 `seed_demo.py` |
| LLM 报 JSON 解析失败 | Render 节点会自动兜底；也可把 LLM 提示词里的输出要求再强调一次，或换更强模型 |
| Docker 里访问不到宿主机 | 见第 6 节 `extra_hosts` / 防火墙 / 局域网 IP |
| Windows 中文路径报错 | PowerContext 数据默认放 `%LOCALAPPDATA%\Moonfall`（ASCII）；不要改到中文路径 |
| 端口 8099 被占用 | `netstat -ano | findstr :8099`，或改 `--port` 并同步 DSL 环境变量 |

---

## 12. 停止与清理

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
```

Linux：

```bash
bash scripts/stop.sh
```

删除 `%LOCALAPPDATA%\Moonfall\powercontext`（Linux 为 `~/.local/share/moonfall/powercontext`）会清空所有记忆；`logs/` 可安全删除。
