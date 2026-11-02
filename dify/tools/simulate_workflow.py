# -*- coding: utf-8 -*-
"""不启动 Dify 也能跑通整份 DSL 的轻量执行器（用于验收与证据）。

它按 DSL 的节点/边顺序执行 start -> code -> http-request -> llm -> code -> http -> answer，
变量插值、HTTP JSON body、错误兜底都按 DSL 里的配置来。LLM 既可以接
tools/openai_shim.py，也可以接任意 OpenAI 兼容模型。

这不是 Dify 官方运行时，但能证明 DSL 的接线、请求体、Code 节点和
PowerContext 读写是自洽的；真正的 Dify 导入体验仍建议按 runbook 操作。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DSL = ROOT / "dsl" / "moonfall-werewolf.chatflow.yml"
PLACEHOLDER = re.compile(r"\{\{#([^#{}]+)#\}\}")


class WorkflowError(RuntimeError):
    pass


class MiniDify:
    def __init__(
        self,
        dsl_path,
        *,
        powercontext="http://127.0.0.1:8099",
        llm_base="http://127.0.0.1:8101/v1",
        llm_key="sk-local-demo",
        llm_model="moonfall-narrator",
        user_id="sim-user",
        conversation_id="conv-1",
        timeout=60,
    ):
        self.dsl = yaml.safe_load(Path(dsl_path).read_text(encoding="utf-8"))
        graph = self.dsl["workflow"]["graph"]
        self.nodes = {node["id"]: node for node in graph["nodes"]}
        self.edges = graph["edges"]
        self.next_node = {}
        for edge in self.edges:
            self.next_node.setdefault(edge["source"], []).append(edge["target"])
        self.env = {item["name"]: item["value"] for item in self.dsl["workflow"].get("environment_variables") or []}
        self.env["POWERCONTEXT_BASE"] = powercontext
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.outputs = {}
        self.client = httpx.Client(timeout=timeout)
        self.llm_base = llm_base.rstrip("/")
        self.llm_key = llm_key
        self.llm_model = llm_model
        self.logs = []

    # ------------------------------------------------------------------
    # 变量
    # ------------------------------------------------------------------
    def _value(self, selector):
        parts = selector.split(".")
        if len(parts) != 2:
            raise WorkflowError(f"bad selector {selector}")
        node_id, name = parts
        if node_id == "sys":
            return {
                "query": self.query,
                "user_id": self.user_id,
                "conversation_id": self.conversation_id,
            }.get(name, "")
        if node_id == "env":
            return self.env.get(name, "")
        bucket = self.outputs.get(node_id) or {}
        return bucket.get(name)

    def _render(self, text):
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)

        def replace(match):
            value = self._value(match.group(1).strip())
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return PLACEHOLDER.sub(replace, text)

    # ------------------------------------------------------------------
    # 节点
    # ------------------------------------------------------------------
    def _run_start(self, node, start_inputs):
        outputs = {}
        for item in node["data"].get("variables") or []:
            outputs[item["variable"]] = start_inputs.get(item["variable"], "")
        self.outputs[node["id"]] = outputs

    def _run_code(self, node):
        data = node["data"]
        inputs = {}
        for item in data.get("variables") or []:
            inputs[item["variable"]] = self._value(".".join(item["value_selector"]))
        namespace = {"__name__": f"dify_{node['id']}"}
        exec(compile(data["code"], f"<{node['id']}>", "exec"), namespace)
        main = namespace.get("main")
        if not callable(main):
            raise WorkflowError(f"{node['id']} has no main()")
        result = main(**inputs)
        if not isinstance(result, dict):
            raise WorkflowError(f"{node['id']} main() did not return dict")
        self.outputs[node["id"]] = result
        self.logs.append({"node": node["id"], "type": "code", "outputs": sorted(result.keys())})
        return result

    def _run_http(self, node):
        data = node["data"]
        url = self._render(data.get("url") or "")
        body_text = ""
        for item in (data.get("body") or {}).get("data") or []:
            body_text += item.get("value") or ""
        body_text = self._render(body_text)
        headers = json.loads(data.get("headers") or "{}")
        try:
            payload = json.loads(body_text) if body_text.strip() else None
        except Exception as exc:
            raise WorkflowError(f"{node['id']} rendered body is not JSON: {exc}: {body_text[:300]}")
        status = 0
        text = ""
        error = ""
        try:
            response = self.client.post(url, json=payload, headers=headers)
            status = response.status_code
            text = response.text
            response.raise_for_status()
        except Exception as exc:
            error = str(exc)
            defaults = {item["key"]: item["value"] for item in data.get("default_value") or []}
            text = str(defaults.get("body", "{}"))
            status = int(defaults.get("status_code", 0) or 0)
        self.outputs[node["id"]] = {"body": text, "status_code": status}
        self.logs.append(
            {"node": node["id"], "type": "http", "url": url, "status": status, "error": error, "body": text[:400]}
        )

    def _run_llm(self, node):
        data = node["data"]
        messages = []
        for item in data.get("prompt_template") or []:
            messages.append({"role": item.get("role", "user"), "content": self._render(item.get("text") or "")})
        params = ((data.get("model") or {}).get("completion_params") or {})
        try:
            response = self.client.post(
                self.llm_base + "/chat/completions",
                headers={"Authorization": f"Bearer {self.llm_key}", "Content-Type": "application/json"},
                json={
                    "model": self.llm_model,
                    "messages": messages,
                    "temperature": params.get("temperature", 0.9),
                    "max_tokens": params.get("max_tokens", 1200),
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            text = ""
            self.logs.append({"node": node["id"], "type": "llm", "error": str(exc)})
        self.outputs[node["id"]] = {"text": text}
        if text:
            self.logs.append({"node": node["id"], "type": "llm", "chars": len(text), "preview": text[:300]})

    def _run_answer(self, node):
        answer = self._render(node["data"].get("answer") or "")
        self.outputs[node["id"]] = {"answer": answer}
        self.logs.append({"node": node["id"], "type": "answer", "chars": len(answer)})
        return answer

    # ------------------------------------------------------------------
    # 一轮
    # ------------------------------------------------------------------
    def turn(self, query, start_inputs=None):
        self.query = query
        start_inputs = start_inputs or {}
        current = "start"
        answer = ""
        visited = 0
        while current:
            visited += 1
            if visited > 30:
                raise WorkflowError("graph did not terminate")
            node = self.nodes.get(current)
            if node is None:
                raise WorkflowError(f"missing node {current}")
            kind = node["data"]["type"]
            if kind == "start":
                self._run_start(node, start_inputs)
            elif kind == "code":
                self._run_code(node)
            elif kind == "http-request":
                self._run_http(node)
            elif kind == "llm":
                self._run_llm(node)
            elif kind == "answer":
                answer = self._run_answer(node)
            else:
                raise WorkflowError(f"unsupported node type {kind}")
            nexts = self.next_node.get(current) or []
            current = nexts[0] if nexts else None
        return answer

    def state(self):
        return json.loads(self.outputs.get("engine", {}).get("save_text") or "{}")

    def debug(self):
        return json.loads(self.outputs.get("engine", {}).get("debug_json") or "{}")


# ----------------------------------------------------------------------
# 自动操作：只通过 DSL 引擎输出的 save_text 判断，不直接改游戏状态
# ----------------------------------------------------------------------
def choose_action(state):
    phase = state.get("phase")
    role = next((p.get("role") for p in state.get("players", []) if p.get("seat") == 1), "villager")
    alive = [p for p in state.get("players", []) if p.get("alive")]
    npcs = [p for p in alive if p.get("seat") != 1]
    if not npcs:
        return "天亮"
    if phase == "night":
        if role == "seer":
            checked = {item["seat"] for item in state.get("seer_checks", []) if item.get("by") == 1}
            targets = [p["seat"] for p in npcs if p["seat"] not in checked]
            return f"查 {targets[0]}" if targets else "天亮"
        if role == "witch":
            if state.get("night", {}).get("victim") and state.get("witch", {}).get("antidote"):
                return "救"
            return "不救"
        if role == "wolf":
            goods = [p["seat"] for p in npcs if p.get("role") != "wolf"]
            return f"刀 {goods[0]}" if goods else "天亮"
        return "天亮"
    if phase == "hunter":
        return f"开枪 {npcs[0]['seat']}"
    if phase == "day":
        if state.get("chat", 0) < 1:
            return f"我觉得 {npcs[0]['seat']} 号有问题"
        if role == "seer":
            wolves = [item["seat"] for item in state.get("seer_checks", []) if item.get("result") == "狼人"]
            if wolves and any(p["seat"] == wolves[0] for p in alive):
                return f"投 {wolves[0]}"
        return f"投 {npcs[0]['seat']}"
    return "继续"


def play_game(runner, role, max_turns=30, transcript=None):
    turns = []
    query = "开始游戏"
    start_inputs = runner_start_inputs(runner)
    for index in range(max_turns):
        answer = runner.turn(query, start_inputs)
        state = runner.state()
        turns.append(
            {
                "turn": index + 1,
                "query": query,
                "phase": state.get("phase"),
                "role": next((p.get("role") for p in state.get("players", []) if p.get("seat") == 1), ""),
                "answer": answer,
                "memory": runner.outputs.get("engine", {}).get("memory_digest", ""),
                "debug": runner.debug(),
            }
        )
        if transcript is not None:
            transcript.append(turns[-1])
        if state.get("phase") == "ended":
            return turns, state
        if index == 0:
            query = role
            continue
        query = choose_action(state)
    raise WorkflowError("game did not end within max turns")


def runner_start_inputs(runner):
    return {"player_name": "验收员", "memory_id": runner.user_id}


def main():
    parser = argparse.ArgumentParser(description="用轻量执行器跑《月蚀镇》DSL")
    parser.add_argument("--dsl", default=str(DEFAULT_DSL))
    parser.add_argument("--powercontext", default="http://127.0.0.1:8099")
    parser.add_argument("--llm-base", default="http://127.0.0.1:8101/v1")
    parser.add_argument("--llm-key", default="sk-local-demo")
    parser.add_argument("--llm-model", default="moonfall-narrator")
    parser.add_argument("--memory-id", default="sim-demo")
    parser.add_argument("--role", default="seer")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--out", default=str(ROOT / "evidence" / "transcript-simulated.md"))
    parser.add_argument("--report", default=str(ROOT / "evidence" / "logs" / "simulation-report.json"))
    args = parser.parse_args()

    transcript = []
    games = []
    for game_index in range(args.games):
        user_id = args.memory_id
        runner = MiniDify(
            args.dsl,
            powercontext=args.powercontext,
            llm_base=args.llm_base,
            llm_key=args.llm_key,
            llm_model=args.llm_model,
            user_id=user_id,
            conversation_id=f"conv-{game_index + 1}",
        )
        turns, state = play_game(runner, args.role, transcript=transcript)
        games.append(
            {
                "game": game_index + 1,
                "memory_id": user_id,
                "turns": len(turns),
                "winner": state.get("winner"),
                "match": state.get("match"),
                "scope_id": runner.outputs.get("prep_scope", {}).get("scope_id"),
                "log": runner.logs,
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 月蚀镇 · DSL 轻量执行记录", ""]
    for item in transcript:
        lines.append(f"## Turn {item['turn']} · `{item['query']}` · phase={item['phase']} · role={item['role']}")
        lines.append("")
        lines.append(item["answer"])
        lines.append("")
        lines.append(f"<!-- memory: {item['memory'][:200]} -->")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "dsl": args.dsl,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "games": games,
        "turns": len(transcript),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(transcript)} turns)")
    print(f"wrote {report_path}")
    for game in games:
        print(
            f"game {game['game']}: winner={game['winner']} role={game['match'].get('role') if game['match'] else '?'} "
            f"turns={game['turns']} scope={game['scope_id']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
