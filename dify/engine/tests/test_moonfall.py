# -*- coding: utf-8 -*-
"""月蚀镇规则引擎单元测试。

运行：
    python -m unittest discover -s engine/tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine import moonfall as m  # noqa: E402
from engine import render  # noqa: E402


def entries(*texts):
    return json.dumps({"entries": [{"kind": "save", "text": text} for text in texts if text]}, ensure_ascii=False)


def setup(role="seer", scope="scp_test", name="测试者"):
    first = m.handle_turn("开始游戏", scope, entries(), name, "")
    second = m.handle_turn(role, scope, entries(first["save_text"]), name, "")
    return first, second


def state_of(result):
    return json.loads(result["save_text"])


def alive_npcs(state):
    return [item for item in state["players"] if item["alive"] and item["seat"] != 1]


def choose_action(state):
    phase = state["phase"]
    role = next(item["role"] for item in state["players"] if item["seat"] == 1)
    alive = [item for item in state["players"] if item["alive"]]
    npcs = [item for item in alive if item["seat"] != 1]
    if not npcs:
        return "天亮"
    if phase == "night":
        if role == "seer":
            checked = {item["seat"] for item in state.get("seer_checks", []) if item.get("by") == 1}
            targets = [item["seat"] for item in npcs if item["seat"] not in checked]
            return f"查 {targets[0]}" if targets else "不查"
        if role == "witch":
            victim = state.get("night", {}).get("victim")
            if victim and state.get("witch", {}).get("antidote"):
                return "救"
            return "不救"
        if role == "wolf":
            goods = [item["seat"] for item in npcs if item["role"] != "wolf"]
            return f"刀 {goods[0]}" if goods else "天亮"
        return "天亮"
    if phase == "hunter":
        return f"开枪 {npcs[0]['seat']}"
    if phase == "day":
        if state.get("chat", 0) < 1:
            return f"我觉得 {npcs[0]['seat']} 号有问题"
        if role == "seer":
            wolves = [item["seat"] for item in state.get("seer_checks", []) if item.get("result") == "狼人"]
            if wolves and any(item["seat"] == wolves[0] for item in alive):
                return f"投 {wolves[0]}"
        return f"投 {npcs[0]['seat']}"
    return "继续"


def play(role, scope="scp_auto", name="自动"):
    state_text = None
    query = "开始游戏"
    for step in range(60):
        result = m.handle_turn(query, scope, entries(state_text), name, "")
        state_text = result["save_text"]
        state = json.loads(state_text)
        if state["phase"] == "ended":
            return result, state, step + 1
        if step == 0:
            query = role
            continue
        query = choose_action(state)
    raise AssertionError("game did not end within 60 turns: " + role)


class RoleTests(unittest.TestCase):
    def test_setup_enters_role_select(self):
        result = m.handle_turn("开始游戏", "scp_a", entries(), "阿远", "")
        state = state_of(result)
        self.assertEqual(state["phase"], "role_select")
        self.assertEqual(state["player_name"], "阿远")
        self.assertIn("选择你的身份", result["answer_fallback"])

    def test_role_can_be_chosen_in_first_message(self):
        result = m.handle_turn("开始游戏，我想当预言家", "scp_onestep", entries(), "阿远", "")
        state = state_of(result)
        self.assertEqual(state["phase"], "night")
        self.assertEqual(state["players"][0]["role"], "seer")

    def test_each_role_composition(self):
        for role in ("seer", "witch", "hunter", "villager", "wolf"):
            with self.subTest(role=role):
                _first, second = setup(role, scope="scp_comp_" + role)
                state = state_of(second)
                roles = [item["role"] for item in state["players"]]
                self.assertEqual(roles.count("wolf"), 2)
                self.assertEqual(roles.count("seer"), 1)
                self.assertEqual(roles.count("witch"), 1)
                self.assertEqual(roles.count("hunter"), 1)
                self.assertEqual(roles.count("villager"), 3)
                self.assertEqual(state["players"][0]["role"], role)
                self.assertEqual(state["phase"], "night")

    def test_first_night_player_is_protected(self):
        for index in range(10):
            _first, second = setup("seer", scope=f"scp_protect_{index}")
            state = state_of(second)
            self.assertTrue(state["players"][0]["alive"])
            self.assertNotEqual(state["night"]["victim"], 1)


class NightTests(unittest.TestCase):
    def test_seer_check_result_recorded(self):
        _first, second = setup("seer", scope="scp_seer")
        third = m.handle_turn("查 3", "scp_seer", entries(second["save_text"]), "测试者", "")
        state = state_of(third)
        self.assertEqual(state["phase"], "day")
        checks = state["seer_checks"]
        self.assertTrue(any(item["by"] == 1 and item["seat"] == 3 for item in checks))

    def test_seer_can_skip(self):
        _first, second = setup("seer", scope="scp_seer_skip")
        third = m.handle_turn("不查", "scp_seer_skip", entries(second["save_text"]), "测试者", "")
        state = state_of(third)
        self.assertEqual(state["phase"], "day")
        self.assertEqual([item for item in state["seer_checks"] if item["by"] == 1], [])

    def test_witch_save_consumes_antidote(self):
        _first, second = setup("witch", scope="scp_witch")
        state = state_of(second)
        victim = state["night"]["victim"]
        self.assertTrue(victim)
        third = m.handle_turn("救", "scp_witch", entries(second["save_text"]), "测试者", "")
        state = state_of(third)
        self.assertFalse(state["witch"]["antidote"])
        self.assertTrue(state["players"][victim - 1]["alive"])

    def test_wolf_cannot_kill_teammate(self):
        _first, second = setup("wolf", scope="scp_wolf")
        state = state_of(second)
        mate = next(item["seat"] for item in state["players"] if item["role"] == "wolf" and item["seat"] != 1)
        third = m.handle_turn(f"刀 {mate}", "scp_wolf", entries(second["save_text"]), "测试者", "")
        state = state_of(third)
        self.assertEqual(state["phase"], "night")
        self.assertEqual(state["night"].get("wolf_target", 0), 0)

    def test_vote_requires_day(self):
        _first, second = setup("seer", scope="scp_vote_night")
        third = m.handle_turn("投 3", "scp_vote_night", entries(second["save_text"]), "测试者", "")
        state = state_of(third)
        self.assertEqual(state["phase"], "night")


class FullGameTests(unittest.TestCase):
    def test_all_roles_finish_and_keep_match(self):
        for role in ("seer", "witch", "hunter", "villager", "wolf"):
            with self.subTest(role=role):
                result, state, turns = play(role, scope="scp_play_" + role)
                self.assertEqual(state["status"], "ended")
                self.assertIn(state["winner"], ("wolf", "good"))
                self.assertIsInstance(state["match"], dict)
                self.assertIn("impressions", state["match"])
                self.assertLessEqual(len(result["save_text"].encode("utf-8")), m.MAX_SAVE_BYTES + 200)
                self.assertGreaterEqual(turns, 3)

    def test_restart_confirmation(self):
        _first, second = setup("seer", scope="scp_restart")
        ask = m.handle_turn("重开", "scp_restart", entries(second["save_text"]), "测试者", "")
        self.assertIn("确认重开", ask["answer_fallback"])
        restart = m.handle_turn("重开确认", "scp_restart", entries(second["save_text"]), "测试者", "")
        self.assertEqual(state_of(restart)["phase"], "role_select")


class MemoryTests(unittest.TestCase):
    def test_memory_dedup_prefers_ended(self):
        active = {
            "v": 1,
            "gid": "g1",
            "status": "active",
            "turn": 3,
            "phase": "day",
            "players": [{"seat": 1, "role": "seer", "alive": True}],
        }
        ended = dict(active)
        ended.update(
            {
                "status": "ended",
                "turn": 4,
                "phase": "ended",
                "match": {"no": 1, "role": "seer", "winner": "good", "result": "win", "impressions": {"2": -1}},
            }
        )
        parsed = m._parse_memory(entries(json.dumps(active, ensure_ascii=False), json.dumps(ended, ensure_ascii=False)))
        self.assertIsNone(parsed["active"])
        self.assertEqual(len(parsed["matches"]), 1)

    def test_cross_game_memory_and_relations(self):
        _result, state, _turns = play("wolf", scope="scp_mem_cross")
        ended_text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        recall = entries(ended_text)
        fresh = m.handle_turn("开始游戏", "scp_mem_cross", recall, "测试者", "")
        self.assertIn("第 1 局", fresh["answer_fallback"])
        self.assertIn("狼人", fresh["answer_fallback"])
        role = m.handle_turn("预言家", "scp_mem_cross", entries(ended_text, fresh["save_text"]), "测试者", "")
        state2 = state_of(role)
        self.assertTrue(any(value < 0 for value in state2["relations"].values()))
        self.assertEqual(state2["match_no"], 2)

    def test_recap_without_active(self):
        match = {
            "no": 1,
            "gid": "g1",
            "role": "seer",
            "winner": "good",
            "result": "win",
            "impressions": {"2": -1},
            "highlight": "测试",
        }
        ended = {
            "v": 1,
            "gid": "g1",
            "status": "ended",
            "turn": 5,
            "phase": "ended",
            "players": [{"seat": 1, "role": "seer", "alive": True}],
            "match": match,
        }
        result = m.handle_turn("复盘", "scp_recap", entries(json.dumps(ended, ensure_ascii=False)), "测试者", "")
        self.assertIn("上一局复盘", result["answer_fallback"])


class RenderTests(unittest.TestCase):
    def test_llm_merge_and_fallback(self):
        _first, second = setup("seer", scope="scp_render")
        scene = second["scene_json"]
        good = json.dumps(
            {
                "narration": "烛火灭了。",
                "speeches": [{"seat": 2, "text": "我抡铁锤的，不讲虚的。"}],
            },
            ensure_ascii=False,
        )
        out = render.main(scene, good, second["save_text"], second["save_text_json"], True)
        self.assertTrue(out["llm_used"])
        self.assertIn("你的身份", out["answer"])
        bad = render.main(scene, "not json", second["save_text"], second["save_text_json"], True)
        self.assertFalse(bad["llm_used"])
        self.assertIn("你的身份", bad["answer"])
        self.assertEqual(bad["save_text"], second["save_text"])
        malformed = json.dumps({"narration": "x", "speeches": "oops"}, ensure_ascii=False)
        weird = render.main(scene, malformed, second["save_text"], second["save_text_json"], True)
        self.assertIn("你的身份", weird["answer"])


if __name__ == "__main__":
    unittest.main()
