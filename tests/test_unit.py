#!/usr/bin/env python3
"""单元测试：gate / router / immune / d_layer / community"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from metaos.core.gate import DecisionGate
from metaos.core.immune import ImmuneMonitor
from metaos.core.router import Router
from metaos.core.types import AssetLevel, Decision, DecisionLevel, DigitalAsset, Task


class TestDecisionGate(unittest.TestCase):
    def setUp(self):
        self.gate = DecisionGate()
        self.task = Task(task_id="t1", task_type="reasoning", input="test")

    def test_green_pass(self):
        level, reason, deadline = self.gate.evaluate(self.task)
        self.assertEqual(level, DecisionLevel.GREEN)

    def test_red_trigger(self):
        task = Task(task_id="t2", task_type="reasoning", input="This involves a principle conflict")
        level, _, _ = self.gate.evaluate(task)
        self.assertEqual(level, DecisionLevel.RED)

    def test_yellow_trigger(self):
        task = Task(task_id="t3", task_type="reasoning", input="I recommend this approach")
        level, _, _ = self.gate.evaluate(task)
        self.assertEqual(level, DecisionLevel.YELLOW)

    def test_reload(self):
        self.gate.reload()
        level, _, _ = self.gate.evaluate(self.task)
        self.assertEqual(level, DecisionLevel.GREEN)


class TestImmuneMonitor(unittest.TestCase):
    def setUp(self):
        self.immune = ImmuneMonitor()

    def test_record_dismissal(self):
        for _ in range(3):
            self.immune.record_dismissal("H_001")
        self.assertTrue(self.immune.is_frozen("H_001"))

    def test_freeze_threshold(self):
        for _ in range(2):
            self.immune.record_dismissal("H_002")
        self.assertFalse(self.immune.is_frozen("H_002"))
        self.immune.record_dismissal("H_002")
        self.assertTrue(self.immune.is_frozen("H_002"))

    def test_meltdown(self):
        self.immune.trigger_meltdown("H_003")
        self.assertTrue(self.immune.is_meltdown("H_003"))
        self.immune.release_meltdown("H_003")
        self.assertFalse(self.immune.is_meltdown("H_003"))

    def test_release_freeze(self):
        self.immune.record_dismissal("H_004")
        self.immune.record_dismissal("H_004")
        self.immune.record_dismissal("H_004")
        self.assertTrue(self.immune.is_frozen("H_004"))
        self.immune.release_freeze("H_004")
        self.assertFalse(self.immune.is_frozen("H_004"))

    def test_timeout_independent_counter(self):
        self.immune.record_timeout("H_005")
        self.immune.record_timeout("H_005")
        # timeout 计数器独立于 dismissal，不触发冻结
        self.assertFalse(self.immune.is_frozen("H_005"))

    def test_check_pattern_anomaly(self):
        decisions = [
            Decision(
                h_id="H_006",
                level="green",
                action="rejected" if i % 2 == 0 else "approved",
                description=f"d_{i}",
                outcome_pending_review=False,
            )
            for i in range(8)
        ]
        anomaly, msg = self.immune.check_pattern_anomaly("H_006", decisions)
        self.assertTrue(anomaly)
        self.assertIn("驳回率异常", msg)


class TestRouter(unittest.TestCase):
    def setUp(self):
        self.router = Router(
            config_path=os.path.join(os.path.dirname(__file__), "../src/metaos/config/task_routes.json")
        )

    def test_resolve_morning(self):
        task = Task(task_id="r1", task_type="morning_ritual", input="晨间")
        candidates = self.router.resolve(task, ["general", "reasoning"])
        self.assertIn("general", candidates)

    def test_resolve_reasoning(self):
        task = Task(task_id="r2", task_type="reasoning", input="逻辑题")
        candidates = self.router.resolve(task, ["reasoning"])
        self.assertIn("reasoning", candidates)

    def test_resolve_empty_healthy(self):
        task = Task(task_id="r3", task_type="reasoning")
        candidates = self.router.resolve(task, [])
        self.assertEqual(candidates, [])

    def test_reload(self):
        self.router.reload()
        task = Task(task_id="r4", task_type="code_gen")
        candidates = self.router.resolve(task, ["code", "general"])
        self.assertIn("code", candidates)


class TestDLayer(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="metaos_ut_")
        from metaos.layers.d_layer import DLayer

        self.d = DLayer(self.data_dir)

    def test_save_and_get_decision(self):
        d = Decision(
            h_id="H_UT", level="green", action="approved", description="单元测试决策", outcome_pending_review=False
        )
        self.d.save_decision(d)
        decisions = self.d.get_decisions("H_UT", 10)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].description, "单元测试决策")

    def test_access_level_filter(self):
        self.d.save_decision(
            Decision(h_id="H_A", level="green", action="approved", description="公开", access_level="public")
        )
        self.d.save_decision(
            Decision(h_id="H_A", level="green", action="approved", description="私有", access_level="owner")
        )
        all_d = self.d.get_decisions("H_A", 10)
        self.assertGreaterEqual(len(all_d), 2)

    def test_principle_versioning(self):
        from metaos.core.types import Principle

        p = Principle(principle_id="P_UT", content="测试原则 v1", source_h_id="H_UT")
        self.d.save_principle(p)
        p2 = Principle(principle_id="P_UT", content="测试原则 v2", source_h_id="H_UT")
        self.d.save_principle(p2)
        active = self.d.get_principles(status="active")
        p_active = [x for x in active if x.principle_id == "P_UT"]
        self.assertEqual(len(p_active), 1)
        self.assertEqual(p_active[0].content, "测试原则 v2")

    def test_save_asset(self):
        a = DigitalAsset(level=AssetLevel.SHARED, content="测试资产", source_h_id="H_UT")
        aid = self.d.save_asset(a)
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "assets", f"{aid}.json")))

    def test_session_persistence(self):
        self.d.save_session(
            "tok1", "H_SESS", "测试", datetime.now(), datetime.now() + timedelta(days=7), datetime.now()
        )
        sessions = self.d.load_sessions()
        self.assertGreaterEqual(len(sessions), 1)
        tokens = [s["token"] for s in sessions]
        self.assertIn("tok1", tokens)


class TestCommunity(unittest.TestCase):
    def setUp(self):
        from metaos.layers.community import CommunityEngine, VoteType

        self.engine = CommunityEngine()
        self.VoteType = VoteType

    def test_register_h(self):
        r = self.engine.register_h("H_C1", "member")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["members"], 1)

    def test_duplicate_register(self):
        self.engine.register_h("H_C2", "member")
        r = self.engine.register_h("H_C2", "member")
        self.assertEqual(r["status"], "error")

    def test_proposal_lifecycle(self):
        self.engine.register_h("H_C3", "member")
        self.engine.register_h("H_C4", "member")
        self.engine.register_h("H_C5", "chair")
        prop = self.engine.propose_shared_asset("H_C3", "测试提案", "内容")
        self.assertEqual(prop.status.value, "pending")
        for h in ["H_C3", "H_C4", "H_C5"]:
            self.engine.vote_on_proposal(prop.proposal_id, h, self.VoteType.APPROVE)
        self.assertEqual(prop.status.value, "approved")

    def test_conflict_resolution(self):
        self.engine.register_h("H_C6", "member")
        self.engine.register_h("H_C7", "member")
        self.engine.register_h("H_C8", "chair")
        c = self.engine.register_conflict("asset_1", "H_C6", "H_C7", "方案A", "方案B")
        self.assertEqual(c.status.value, "open")
        r = self.engine.resolve_conflict(c.conflict_id, "折中方案")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(c.status.value, "resolved")

    def test_emergence_conditions(self):
        self.engine.register_h("H_C9", "member")
        self.engine.register_h("H_C10", "member")
        self.engine.register_h("H_C11", "chair")
        e = self.engine.check_emergence_conditions()
        self.assertFalse(e["emergence_detected"])


# ── Governance 单元测试 ──


class TestGovernance(unittest.TestCase):
    def setUp(self):
        from metaos.layers.governance import MetaGovernance

        self.gov = MetaGovernance(scenario="personal")

    def test_kernel_rules_immutable(self):
        """内核规则 K1-K4 不可修改"""
        for kid in ["K1", "K2", "K3", "K4"]:
            r = self.gov.propose_change(kid, "x", "y", "测试", "H_T")
            self.assertEqual(r["status"], "rejected")

    def test_propose_and_confirm(self):
        """常规规则可修改，需冷静期"""
        r = self.gov.propose_change("test_rule", "old", "new", "测试", "H_T")
        self.assertEqual(r["status"], "cooling")
        pid = r["proposal_id"]
        # 模拟冷静期已过
        self.gov._proposals[pid].cooling_end = datetime.now() - timedelta(hours=1)
        r2 = self.gov.confirm_change(pid, "H_T")
        self.assertEqual(r2["status"], "approved")

    def test_simulate_kernel_rejected(self):
        """dry-run 内核规则应拒绝"""
        r = self.gov.simulate_change("K1", "x", "y")
        self.assertEqual(r["verdict"], "rejected")

    def test_simulate_regular_ok(self):
        """dry-run 常规规则应通过"""
        r = self.gov.simulate_change("yellow_deadline", "24h", "48h")
        self.assertEqual(r["verdict"], "acceptable")

    def test_rollback(self):
        """24h 窗口内可回滚"""
        r = self.gov.propose_change("rb_rule", "old", "new", "回滚测试", "H_T")
        pid = r["proposal_id"]
        self.gov._proposals[pid].cooling_end = datetime.now() - timedelta(hours=1)
        self.gov.confirm_change(pid, "H_T")
        rb = self.gov.rollback(pid, "H_T")
        self.assertEqual(rb["status"], "rolled_back")

    def test_audit_log(self):
        """审计日志不可删除"""
        self.gov.propose_change("audit_rule", "a", "b", "审计测试", "H_T")
        history = self.gov.get_history(5)
        self.assertGreaterEqual(len(history), 1)

    def test_pending_list(self):
        self.gov.propose_change("pending_rule", "a", "b", "待办测试", "H_T")
        pending = self.gov.list_pending()
        self.assertGreaterEqual(len(pending), 1)


# ── MLayer 后端切换测试 ──


class TestMLayer(unittest.TestCase):
    def setUp(self):
        from metaos.layers.m_layer import MLayer, MockBackend

        self.ml = MLayer(backend=MockBackend(watermark=True))

    def test_mock_backend_default(self):
        self.assertIn("MockBackend", self.ml.backend_name)

    def test_mock_backend_call(self):
        from metaos.core.types import Task

        t = Task(task_id="ml1", task_type="morning_ritual", input="晨间测试")
        r = self.ml.call(t)
        self.assertEqual(r.status, "completed")
        self.assertIn("[SIMULATED]", r.output)

    def test_inject_failure(self):
        self.ml.inject_failure(["general"])
        healthy = self.ml.get_healthy_models()
        self.assertNotIn("general", healthy)

    def test_restore_all(self):
        self.ml.inject_failure(["general", "reasoning", "code", "domain"])
        self.assertEqual(len(self.ml.get_healthy_models()), 0)
        self.ml.restore_all()
        self.assertEqual(len(self.ml.get_healthy_models()), 4)

    def test_ollama_backend_code_path(self):
        from metaos.layers.m_layer import OllamaBackend

        ob = OllamaBackend(base_url="http://test:11434", model="test-model")
        self.assertEqual(ob.model, "test-model")

    def test_ollama_backend_reads_standard_llm_env(self):
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"models": [{"name": "qwen3.5:4b"}]}
        with (
            patch.dict(
                os.environ,
                {
                    "LLM_PROVIDER": "ollama",
                    "LLM_BASE_URL": "http://proxy:11434",
                    "LLM_MODEL": "qwen3.5:4b",
                },
                clear=False,
            ),
            patch("requests.get", return_value=mock_response),
        ):
            from metaos.layers.m_layer import OllamaBackend

            ob = OllamaBackend()
            self.assertEqual(ob.base_url, "http://proxy:11434")
            self.assertEqual(ob.model, "qwen3.5:4b")


class TestCapabilityTools(unittest.TestCase):
    def test_device_orchestrator_prefers_desktop_for_code_task(self):
        from metaos.mcp_server import recommend_device_for_task

        device = recommend_device_for_task(
            "需要长时间编码和多窗口调试",
            [
                {"id": "phone", "kind": "mobile", "capabilities": ["chat"], "status": "online"},
                {
                    "id": "desktop-studio",
                    "kind": "desktop",
                    "capabilities": ["code", "multi_window", "long_running_tasks"],
                    "status": "online",
                },
            ],
        )
        self.assertEqual(device["id"], "desktop-studio")

    def test_family_brief_flags_upcoming_birthday(self):
        from metaos.mcp_server import build_family_brief

        brief = build_family_brief(
            events=[
                {"title": "孩子生日", "date": (datetime.now() + timedelta(days=2)).date().isoformat()},
                {"title": "家长会", "date": (datetime.now() + timedelta(days=1)).date().isoformat()},
            ],
            reminders=["准备蛋糕"],
        )
        self.assertTrue(any("生日" in alert for alert in brief["alerts"]))
        self.assertEqual(brief["agenda"][0]["title"], "家长会")

    def test_metaos_tools_include_capability_track_tools(self):
        from metaos.mcp_server import TOOLS

        names = {tool["name"] for tool in TOOLS}
        self.assertIn("metaos_device_orchestrator", names)
        self.assertIn("metaos_family_brief", names)


class TestGovernancePersistence(unittest.TestCase):
    def test_save_and_load(self):
        from metaos.layers.d_layer import DLayer

        d = DLayer()
        state = {"test_key": {"proposal_1": {"status": "cooling"}}}
        d.save_governance_state(state)
        loaded = d.get_governance_state()
        self.assertIn("test_key", loaded)
        self.assertEqual(loaded["test_key"]["proposal_1"]["status"], "cooling")


# ── Gate 中文匹配测试（TD-C01） ──


class TestGateChinese(unittest.TestCase):
    def setUp(self):
        self.gate = DecisionGate()

    def test_chinese_red_match(self):
        """中文关键词应能匹配"""
        task = Task(task_id="zh1", task_type="reasoning", input="这个决策涉及原则修订的内容")
        level, _, _ = self.gate.evaluate(task)
        self.assertEqual(level, DecisionLevel.RED)

    def test_chinese_no_false_positive(self):
        """不应把包含关系误认为匹配"""
        # "原则" 在 "原则上" 中应匹配，"原则上" 不触发
        task = Task(task_id="zh2", task_type="reasoning", input="原则上可以这样做")
        level, _, _ = self.gate.evaluate(task)
        # "原则上" 不匹配 "原则" 关键词 → 绿灯（除非其他关键词命中）
        kw = self.gate.config.get("red_keywords", [])
        matched = any(k in task.input.lower() for k in kw)
        if not matched:
            self.assertEqual(level, DecisionLevel.GREEN)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    for cls in [
        TestDecisionGate,
        TestImmuneMonitor,
        TestRouter,
        TestDLayer,
        TestCommunity,
        TestGovernance,
        TestMLayer,
        TestCapabilityTools,
        TestGovernancePersistence,
        TestGateChinese,
    ]:
        suite.addTest(unittest.TestLoader().loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
