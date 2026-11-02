# -*- coding: utf-8 -*-
"""离线校验 Dify Chatflow DSL 的结构、变量引用、JSON 请求体与 Code 节点。

这不是 Dify 官方校验器，但它覆盖了导入/运行最容易出错的点：
- 节点/边是否完整、是否从 start 可达 answer；
- {{#node.var#}} 是否指向真实存在的节点输出；
- HTTP body 在变量替换后是否仍是合法 JSON；
- Code 节点的 main 签名、输出字段与本地执行结果是否一致。

运行：python tools/validate_dsl.py [dsl路径]
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DSL = ROOT / "dsl" / "moonfall-werewolf.chatflow.yml"

PLACEHOLDER = re.compile(r"\{\{#([^#{}]+)#\}\}")
CHECKS: list[tuple[bool, str, str]] = []


def check(ok, name, detail=""):
    CHECKS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


def walk_strings(value, path="root"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_strings(item, f"{path}[{index}]")


def output_names(node):
    data = node.get("data") or {}
    kind = data.get("type")
    if kind == "code":
        return set((data.get("outputs") or {}).keys())
    if kind == "http-request":
        return {"body", "status_code"}
    if kind == "llm":
        return {"text", "usage", "finish_reason"}
    if kind == "start":
        return {item.get("variable") for item in data.get("variables") or []}
    return set()


def validate_graph(dsl):
    workflow = dsl.get("workflow") or {}
    graph = workflow.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_map = {node.get("id"): node for node in nodes}
    check(len(nodes) >= 8, "节点数量合理", f"{len(nodes)} nodes")
    check(len(node_map) == len(nodes), "节点 ID 唯一", f"{len(nodes)} unique")
    check(node_map.get("start") is not None, "存在 start 节点")
    check(node_map.get("answer") is not None, "存在 answer 节点")

    types = {node.get("id"): (node.get("data") or {}).get("type") for node in nodes}
    check(all(types.values()), "每个节点都有 type")
    check(types.get("answer") == "answer", "answer 节点类型正确")

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        ok = source in node_map and target in node_map
        check(ok, f"边 {source} -> {target}", "端点存在" if ok else "端点缺失")
        if ok:
            check(
                edge.get("data", {}).get("sourceType") == types.get(source),
                f"边 {source} sourceType 匹配",
                f"{edge.get('data', {}).get('sourceType')} vs {types.get(source)}",
            )
            check(
                edge.get("data", {}).get("targetType") == types.get(target),
                f"边 {target} targetType 匹配",
                f"{edge.get('data', {}).get('targetType')} vs {types.get(target)}",
            )

    adjacency = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], []).append(edge["target"])
    seen = set()
    stack = ["start"]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, []))
    check(seen == set(node_map), "所有节点从 start 可达", f"missing={sorted(set(node_map) - seen)}")
    check("answer" in seen, "answer 从 start 可达")
    return node_map, types


def validate_variables(dsl, node_map):
    env_names = {item.get("name") for item in (dsl.get("workflow") or {}).get("environment_variables") or []}
    declared = {node_id: output_names(node) for node_id, node in node_map.items()}
    ignored_prefixes = {"sys", "env", "conversation"}
    for path, text in walk_strings(dsl):
        for match in PLACEHOLDER.finditer(text):
            selector = match.group(1).strip()
            parts = selector.split(".")
            if len(parts) != 2:
                check(False, f"变量格式 {selector}", path)
                continue
            node_id, variable = parts
            if node_id == "env":
                check(variable in env_names, f"环境变量 {selector}", path)
                continue
            if node_id in ignored_prefixes:
                continue
            check(node_id in node_map, f"变量节点存在 {selector}", path)
            if node_id in node_map:
                check(variable in declared.get(node_id, set()), f"变量输出存在 {selector}", path)


def validate_http(node_map):
    for node_id, node in node_map.items():
        data = node.get("data") or {}
        if data.get("type") != "http-request":
            continue
        url = data.get("url") or ""
        check("{{#env.POWERCONTEXT_BASE#}}" in url, f"{node_id} URL 使用环境变量", url)
        body = ""
        for item in (data.get("body") or {}).get("data") or []:
            body += item.get("value") or ""
        body = body.replace("{{#render.save_text_json#}}", '"__save__"')
        body = PLACEHOLDER.sub("x", body)
        try:
            parsed = json.loads(body)
            ok = isinstance(parsed, dict)
        except Exception as exc:
            parsed = None
            ok = False
            check(False, f"{node_id} body 是合法 JSON", str(exc))
        if parsed is not None:
            check(ok, f"{node_id} body 是 JSON 对象", str(parsed)[:80])
        check(data.get("error_strategy") == "default-value", f"{node_id} 有 HTTP 兜底")
        check(isinstance(data.get("default_value"), list) and data.get("default_value"), f"{node_id} default_value 非空")


def exec_code(node_id, code, kwargs):
    namespace = {"__name__": f"dsl_{node_id}"}
    exec(compile(code, f"<{node_id}>", "exec"), namespace)
    main = namespace.get("main")
    if not callable(main):
        raise AssertionError("no main()")
    signature = inspect.signature(main)
    expected = set(kwargs)
    actual = set(signature.parameters)
    if actual != expected:
        raise AssertionError(f"main signature {sorted(actual)} != inputs {sorted(expected)}")
    return main(**kwargs)


def validate_code(node_map):
    for node_id, node in node_map.items():
        data = node.get("data") or {}
        if data.get("type") != "code":
            continue
        code = data.get("code") or ""
        check(bool(code.strip()), f"{node_id} code 非空", f"{len(code)} chars")
        check("def main(" in code, f"{node_id} 定义 main()")
        check(data.get("code_language") == "python3", f"{node_id} code_language")
        outputs = data.get("outputs") or {}
        check(bool(outputs), f"{node_id} 声明 outputs", f"{len(outputs)} outputs")

    # 本地跑一遍关键链路，确认 Code 节点没有语法/类型问题。
    prep = exec_code(
        "prep",
        node_map["prep"]["data"]["code"],
        {"player_name": "", "memory_id": "demo", "user_id": "user-123"},
    )
    check(prep.get("scope_key") == "moonfall:user:demo", "prep 生成 scope_key", str(prep))
    check(isinstance(prep.get("scope_key_json"), str), "prep scope_key_json 是字符串")

    prep_scope = exec_code(
        "prep_scope",
        node_map["prep_scope"]["data"]["code"],
        {"scope_body": '{"scope_id": "scp_demo"}'},
    )
    check(prep_scope.get("scope_id") == "scp_demo", "prep_scope 解析 scope_id")
    check(prep_scope.get("memory_ok") is True, "prep_scope memory_ok")

    empty_memory = json.dumps({"entries": []}, ensure_ascii=False)
    engine = exec_code(
        "engine",
        node_map["engine"]["data"]["code"],
        {
            "query": "开始游戏",
            "scope_id": "scp_demo",
            "recall_body": empty_memory,
            "player_name": "验证者",
            "memory_id": "demo",
        },
    )
    for key in (
        "answer_fallback",
        "scene_json",
        "brief_json",
        "save_text",
        "save_text_json",
        "should_save",
        "memory_digest",
        "phase",
        "game_id",
        "turn",
        "player_role",
        "debug_json",
    ):
        check(key in engine, f"engine 输出 {key}")
    check(engine.get("phase") == "role_select", "engine 首轮进入 role_select", str(engine.get("phase")))
    check(isinstance(engine.get("should_save"), bool), "engine should_save 是 bool")
    check(json.loads(engine["save_text"]).get("player_name") == "验证者", "engine 存档含玩家称呼")
    check(json.loads(engine["save_text_json"]) == engine["save_text"], "engine save_text_json 转义正确")

    # 第二轮：选身份，进入夜晚。
    recall = json.dumps({"entries": [{"kind": "save", "text": engine["save_text"]}]}, ensure_ascii=False)
    engine2 = exec_code(
        "engine",
        node_map["engine"]["data"]["code"],
        {
            "query": "预言家",
            "scope_id": "scp_demo",
            "recall_body": recall,
            "player_name": "验证者",
            "memory_id": "demo",
        },
    )
    check(engine2.get("phase") == "night", "engine 选身份后进入 night", str(engine2.get("phase")))
    check(engine2.get("player_role") == "预言家", "engine 身份正确", str(engine2.get("player_role")))

    scene = json.loads(engine2["scene_json"])
    check("speaker_plan" in (scene.get("brief") or {}), "scene brief 含 speaker_plan")
    llm_text = json.dumps(
        {
            "narration": "烛火灭了，酒馆里只剩呼吸声。",
            "speeches": [{"seat": 2, "text": "我抡铁锤的，不讲虚的。今晚谁都别乱走。"}],
        },
        ensure_ascii=False,
    )
    render = exec_code(
        "render",
        node_map["render"]["data"]["code"],
        {
            "scene_json": engine2["scene_json"],
            "llm_text": llm_text,
            "save_text": engine2["save_text"],
            "save_text_json": engine2["save_text_json"],
            "should_save": engine2["should_save"],
        },
    )
    for key in ("answer", "save_text", "save_text_json", "should_save", "llm_used"):
        check(key in render, f"render 输出 {key}")
    check("你的身份" in render.get("answer", ""), "render 保留私密身份")
    check(render.get("llm_used") is True, "render 识别 LLM JSON")
    check(render.get("save_text") == engine2["save_text"], "render 透传存档")

    render_bad = exec_code(
        "render",
        node_map["render"]["data"]["code"],
        {
            "scene_json": engine2["scene_json"],
            "llm_text": "对不起，我不会输出 JSON。",
            "save_text": engine2["save_text"],
            "save_text_json": engine2["save_text_json"],
            "should_save": engine2["should_save"],
        },
    )
    check("你的身份" in render_bad.get("answer", ""), "render 抽风时仍有完整兜底")
    check(render_bad.get("llm_used") is False, "render 标记未使用 LLM")


def validate_graphon_nodes(node_map):
    try:
        from graphon.nodes.answer.entities import AnswerNodeData
        from graphon.nodes.code.entities import CodeNodeData
        from graphon.nodes.http_request.entities import HttpRequestNodeData
        from graphon.nodes.llm.entities import LLMNodeData
        from graphon.nodes.start.entities import StartNodeData
    except ImportError:
        print("[SKIP] graphon node entities 未安装，跳过官方节点模型校验")
        return

    models = {
        "start": StartNodeData,
        "code": CodeNodeData,
        "http-request": HttpRequestNodeData,
        "llm": LLMNodeData,
        "answer": AnswerNodeData,
    }
    for node_id, node in node_map.items():
        kind = (node.get("data") or {}).get("type")
        model = models.get(kind)
        if model is None:
            continue
        try:
            model.model_validate(node["data"])
            check(True, f"graphon 节点模型 {node_id}", kind)
        except Exception as exc:
            check(False, f"graphon 节点模型 {node_id}", str(exc)[:300])


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DSL
    print(f"DSL: {path}")
    dsl = yaml.safe_load(path.read_text(encoding="utf-8"))
    check(isinstance(dsl, dict), "YAML 可解析")
    check(dsl.get("kind") == "app", "kind=app")
    check(dsl.get("version") == "0.3.1", "DSL version 0.3.1", str(dsl.get("version")))
    check((dsl.get("app") or {}).get("mode") == "advanced-chat", "mode=advanced-chat")
    check(bool((dsl.get("app") or {}).get("name")), "应用名称非空")
    check(isinstance(dsl.get("dependencies"), list), "dependencies 是列表")
    check((dsl.get("workflow") or {}).get("conversation_variables") == [], "conversation_variables 为空")

    node_map, _types = validate_graph(dsl)
    validate_variables(dsl, node_map)
    validate_http(node_map)
    validate_code(node_map)
    validate_graphon_nodes(node_map)

    # Dify 1.17 的 DSL 解析器（graphon）如果能导入，就再做一次官方结构校验。
    try:
        from graphon.dsl import importer

        plan = importer.inspect(path.read_text(encoding="utf-8"))
        status = str(getattr(plan.load_status, "value", plan.load_status))
        check(status == "loadable", "graphon 官方 DSL 解析", f"status={status} reason={plan.load_reason}")
        check(list(plan.dependencies) == [], "graphon 依赖列表", str(plan.dependencies))
    except ImportError:
        print("[SKIP] graphon 未安装，跳过官方 DSL 解析")
    except Exception as exc:
        check(False, "graphon 官方 DSL 解析", str(exc))

    failed = [item for item in CHECKS if not item[0]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    if failed:
        for _ok, name, detail in failed:
            print(f"  FAIL: {name} {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
