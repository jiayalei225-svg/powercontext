# 运行证据说明

本目录记录《月蚀镇》在一次真实本地运行中产生的材料。所有内容均为虚构游戏数据，不含 API Key、密码或个人信息。

## 环境

| 项目 | 值 |
|---|---|
| OS | Windows 11 |
| Python | 3.13.15（64 位） |
| PowerContext | 1.4.1（`powercontext[server]`，SQLite 后端） |
| Dify | 目标版本 1.17.0；本机未启动完整 Dify（无 Docker），使用 Dify 1.17 的 `graphon` DSL 解析器与节点模型做官方结构校验 |
| LLM | 本地 `tools/openai_shim.py`（无真实 Key；用于让验收可重复） |
| 时间 | 2026-11-02 |

> **关于 Dify 截图的说明**：本机没有 Docker/Dify 运行时，因此没有伪造 Dify 界面截图。Dify 侧的证据是：
> 1. `dsl-validation.txt` 中 `graphon` 官方解析结果 `loadable`；
> 2. 每个节点的 `StartNodeData` / `CodeNodeData` / `HttpRequestNodeData` / `LLMNodeData` / `AnswerNodeData` 校验通过；
> 3. `verify-transcript.md` 是按 DSL 节点顺序执行的真实链路（start → 3 个 HTTP → code → LLM → code → HTTP → answer），不是直接调用引擎。
>
> 评审在 Dify 中导入 DSL 后，运行历史里的三个 HTTP 节点会给出同等甚至更直接的证据。

## 文件

| 文件 | 说明 |
|---|---|
| `logs/verify-report.json` | `scripts/verify.py` 的机器可读结果：14 项断言、scope_id、match、回合数 |
| `verify-transcript.md` | 第一局完整对局 + 新会话历史战绩 + 新会话中途续局 |
| `logs/dsl-validation.txt` | DSL 结构/变量/HTTP JSON/Code/graphon 校验输出（136 项） |
| `logs/unit-tests.txt` | 引擎单元测试（15 项） |
| `logs/simulation-report.json` | 两局连续模拟报告 |
| `transcript-simulated.md` | 两局连续模拟的完整对话 |
| `logs/powercontext-demo.json` | demo Scope 的 3 条真实记忆：两局 ended + 一局 active |
| `logs/demo-seed.txt` | `seed_demo.py` 输出 |

## 复现

```powershell
cd dify
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
.venv\Scripts\python.exe scripts\seed_demo.py
.venv\Scripts\python.exe tools\validate_dsl.py
.venv\Scripts\python.exe -m unittest discover -s engine\tests -v
.venv\Scripts\python.exe scripts\verify.py
```

> `verify.py` 会在 8101 没有 shim 时自动尝试启动；如果已有真实模型，可以把 DSL 的 LLM 节点换成真实模型，再跳过 shim。

## 数据清理

- 本目录中的 scope_id、gid 是这次运行的随机值，不代表任何真实用户；
- demo 档案可以用 `seed_demo.py` 重新生成；
- 如需清空本机所有记忆，删除 `%LOCALAPPDATA%\Moonfall\powercontext`（Linux：`~/.local/share/moonfall/powercontext`）。
