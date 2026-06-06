#!/usr/bin/env python3
"""单元测试：Deadlock Detector — DFS 环检测 + 超时 + READONLY 释放策略"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from metaos.deadlock_detector import READONLY_MSG, DeadlockDetector


class TestRegisterAgent(unittest.TestCase):
    """Agent 注册"""

    def setUp(self):
        self.dd = DeadlockDetector()

    def test_register_single_agent(self):
        r = self.dd.register_agent("agent-a", priority=2)
        self.assertEqual(r["ok"], True)
        self.assertEqual(r["agent_id"], "agent-a")
        self.assertIn("agent-a", self.dd._agent_priority)
        self.assertEqual(self.dd._agent_priority["agent-a"], 2)

    def test_register_default_priority(self):
        self.dd.register_agent("agent-a")
        self.assertEqual(self.dd._agent_priority["agent-a"], 2)

    def test_register_multiple_agents(self):
        for aid, pri in [("agent-a", 0), ("agent-b", 1), ("agent-c", 2), ("agent-d", 3)]:
            self.dd.register_agent(aid, pri)
        self.assertEqual(len(self.dd._agent_priority), 4)
        self.assertEqual(self.dd._agent_priority["agent-a"], 0)
        self.assertEqual(self.dd._agent_priority["agent-d"], 3)

    def test_register_duplicate_updates_priority(self):
        self.dd.register_agent("agent-a", priority=0)
        r = self.dd.register_agent("agent-a", priority=3)
        self.assertEqual(r["ok"], True)
        self.assertEqual(self.dd._agent_priority["agent-a"], 3)

    def test_register_priority_types(self):
        r = self.dd.register_agent("agent-a", priority=0)
        self.assertEqual(r["ok"], True)
        r = self.dd.register_agent("agent-b", priority=3)
        self.assertEqual(r["ok"], True)


class TestAddDependency(unittest.TestCase):
    """添加依赖边"""

    def setUp(self):
        self.dd = DeadlockDetector()
        for a in ["agent-a", "agent-b", "agent-c"]:
            self.dd.register_agent(a)

    def test_add_simple_dependency(self):
        r = self.dd.add_dependency("agent-a", "agent-b")
        self.assertEqual(r["ok"], True)
        self.assertIn("agent-b", self.dd._edges.get("agent-a", {}))

    def test_add_dependency_with_resource_id(self):
        r = self.dd.add_dependency("agent-a", "agent-b", resource_id="lock:db:001")
        self.assertEqual(r["ok"], True)
        self.assertEqual(self.dd._edges["agent-a"]["agent-b"], "lock:db:001")

    def test_add_dependency_unknown_waiter(self):
        r = self.dd.add_dependency("unknown", "agent-b")
        self.assertIn("error", r)

    def test_add_dependency_unknown_held_by(self):
        r = self.dd.add_dependency("agent-a", "unknown")
        self.assertIn("error", r)

    def test_add_duplicate_dependency(self):
        self.dd.add_dependency("agent-a", "agent-b", resource_id="lock:db:001")
        r = self.dd.add_dependency("agent-a", "agent-b", resource_id="lock:db:002")
        self.assertEqual(r["ok"], True)
        # Should update resource_id
        self.assertEqual(self.dd._edges["agent-a"]["agent-b"], "lock:db:002")

    def test_add_multiple_dependencies(self):
        self.dd.register_agent("agent-d")
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-a", "agent-c")
        self.dd.add_dependency("agent-b", "agent-d")
        self.assertEqual(len(self.dd._edges["agent-a"]), 2)
        self.assertEqual(len(self.dd._edges["agent-b"]), 1)
        self.assertIn("agent-c", self.dd._edges["agent-a"])
        self.assertIn("agent-d", self.dd._edges["agent-b"])


class TestRemoveDependency(unittest.TestCase):
    """移除依赖边"""

    def setUp(self):
        self.dd = DeadlockDetector()
        for a in ["agent-a", "agent-b", "agent-c"]:
            self.dd.register_agent(a)
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-a", "agent-c")

    def test_remove_specific_target(self):
        r = self.dd.remove_dependency("agent-a", "agent-b")
        self.assertEqual(r["ok"], True)
        self.assertNotIn("agent-b", self.dd._edges.get("agent-a", {}))
        self.assertIn("agent-c", self.dd._edges["agent-a"])

    def test_remove_all_dependencies(self):
        r = self.dd.remove_dependency("agent-a")
        self.assertEqual(r["ok"], True)
        self.assertNotIn("agent-a", self.dd._edges)

    def test_remove_unknown_waiter(self):
        r = self.dd.remove_dependency("unknown", "agent-b")
        self.assertEqual(r["ok"], True)  # No-op is OK

    def test_remove_nonexistent_target(self):
        r = self.dd.remove_dependency("agent-a", "nonexistent")
        self.assertEqual(r["ok"], True)  # No-op is OK

    def test_remove_after_deadlock_clears(self):
        self.dd.add_dependency("agent-b", "agent-a")
        # Deadlock exists: A→B, A→C, B→A
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        # Remove the cycle edge
        self.dd.remove_dependency("agent-b", "agent-a")
        dl2 = self.dd.detect_deadlocks()
        self.assertEqual(len(dl2), 0)


class TestDeadlockDetection(unittest.TestCase):
    """DFS 环检测"""

    def setUp(self):
        self.dd = DeadlockDetector()
        for a in ["agent-a", "agent-b", "agent-c", "agent-d", "agent-e"]:
            self.dd.register_agent(a)

    def test_no_edge_no_deadlock(self):
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])

    def test_single_edge_no_deadlock(self):
        self.dd.add_dependency("agent-a", "agent-b")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])

    def test_two_node_cycle(self):
        """A waits B, B waits A → deadlock"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        self.assertIn("agent-a", dl[0]["agents_in_cycle"])
        self.assertIn("agent-b", dl[0]["agents_in_cycle"])
        self.assertIn("description", dl[0])
        self.assertIn("cycle", dl[0])

    def test_three_node_cycle(self):
        """A→B→C→A → deadlock"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-c")
        self.dd.add_dependency("agent-c", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        self.assertIn("agent-a", dl[0]["agents_in_cycle"])
        self.assertIn("agent-b", dl[0]["agents_in_cycle"])
        self.assertIn("agent-c", dl[0]["agents_in_cycle"])

    def test_multiple_independent_cycles(self):
        """A→B→A + C→D→C → 2 deadlocks"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        self.dd.add_dependency("agent-c", "agent-d")
        self.dd.add_dependency("agent-d", "agent-c")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 2)

    def test_dag_no_deadlock(self):
        """A→B→C→D (no cycle) → no deadlock"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-c")
        self.dd.add_dependency("agent-c", "agent-d")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])

    def test_large_dag_no_deadlock(self):
        """Tree-like dependency, no cycle"""
        for i in range(10):
            self.dd.register_agent(f"agent-{i}")
        self.dd.add_dependency("agent-0", "agent-1")
        self.dd.add_dependency("agent-0", "agent-2")
        self.dd.add_dependency("agent-1", "agent-3")
        self.dd.add_dependency("agent-1", "agent-4")
        self.dd.add_dependency("agent-2", "agent-5")
        self.dd.add_dependency("agent-2", "agent-6")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])

    def test_self_dependency_not_a_deadlock(self):
        """Agent waiting for itself is a self-loop, not a cross-agent deadlock"""
        self.dd.add_dependency("agent-a", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        self.assertEqual(len(dl[0]["agents_in_cycle"]), 1)
        self.assertIn("agent-a", dl[0]["agents_in_cycle"])

    def test_cycle_includes_unregistered_agent(self):
        """Edge to unregistered agent should be handled gracefully"""
        self.dd.add_dependency("agent-a", "unregistered")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])  # No cycle, just a dangling edge


class TestNoFalsePositive(unittest.TestCase):
    """确保不会错误地将正常依赖标记为死锁"""

    def setUp(self):
        self.dd = DeadlockDetector()
        for a in ["agent-a", "agent-b", "agent-c", "agent-d"]:
            self.dd.register_agent(a)

    def test_tree_dependency_no_deadlock(self):
        """A→B, A→C, B→D (tree) → no deadlock"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-a", "agent-c")
        self.dd.add_dependency("agent-b", "agent-d")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])

    def test_diamond_dependency_no_deadlock(self):
        """A→B→D, A→C→D (diamond) → no deadlock"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-a", "agent-c")
        self.dd.add_dependency("agent-b", "agent-d")
        self.dd.add_dependency("agent-c", "agent-d")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])

    def test_dependency_released_before_check(self):
        """A→B→A created then removed → no deadlock"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        self.dd.remove_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(dl, [])


class TestTimeout(unittest.TestCase):
    """超时检测"""

    def setUp(self):
        self.dd = DeadlockDetector()
        self.dd.register_agent("agent-a")
        self.dd.register_agent("agent-b")

    def test_no_timeout_under_threshold(self):
        with patch("time.time", return_value=100.0):
            self.dd.add_dependency("agent-a", "agent-b")
        with patch("time.time", return_value=100.0 + 299):  # < 5 min
            timed_out = self.dd.check_timeouts()
        self.assertEqual(timed_out, [])

    def test_timeout_over_threshold(self):
        with patch("time.time", return_value=100.0):
            self.dd.add_dependency("agent-a", "agent-b")
        with patch("time.time", return_value=100.0 + 301):  # > 5 min
            timed_out = self.dd.check_timeouts()
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(timed_out[0]["agent_id"], "agent-a")
        self.assertTrue(timed_out[0]["timed_out"])
        self.assertIn("waits_for", timed_out[0])
        self.assertIn("wait_seconds", timed_out[0])
        self.assertEqual(timed_out[0]["wait_seconds"], 301)

    def test_multiple_timeouts(self):
        self.dd.register_agent("agent-c")
        with patch("time.time", return_value=100.0):
            self.dd.add_dependency("agent-a", "agent-b")
            self.dd.add_dependency("agent-c", "agent-a")
        with patch("time.time", return_value=100.0 + 600):
            timed_out = self.dd.check_timeouts()
        self.assertEqual(len(timed_out), 2)

    def test_timeout_cleared_after_remove(self):
        with patch("time.time", return_value=100.0):
            self.dd.add_dependency("agent-a", "agent-b")
            self.dd.remove_dependency("agent-a", "agent-b")
        with patch("time.time", return_value=100.0 + 600):
            timed_out = self.dd.check_timeouts()
        self.assertEqual(timed_out, [])

    def test_exact_threshold_no_timeout(self):
        """Wait exactly 300 seconds should NOT be flagged"""
        with patch("time.time", return_value=100.0):
            self.dd.add_dependency("agent-a", "agent-b")
        with patch("time.time", return_value=100.0 + 300):
            timed_out = self.dd.check_timeouts()
        self.assertEqual(timed_out, [])


class TestResolveDeadlock(unittest.TestCase):
    """死锁释放策略"""

    def setUp(self):
        self.dd = DeadlockDetector()

    def test_resolve_terminates_lowest_priority(self):
        self.dd.register_agent("agent-a", priority=0)  # highest
        self.dd.register_agent("agent-b", priority=3)  # lowest
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        r = self.dd.resolve_deadlock(dl[0])
        self.assertEqual(r["suggested"], True)
        self.assertEqual(r["terminate_agent"], "agent-b")
        self.assertIn("reason", r)
        self.assertIn("lowest_priority", r["reason"])

    def test_resolve_is_readonly(self):
        self.dd.register_agent("agent-a", priority=1)
        self.dd.register_agent("agent-b", priority=2)
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        r = self.dd.resolve_deadlock(dl[0])
        self.assertIn("message", r)
        self.assertEqual(r["message"], READONLY_MSG)

    def test_resolve_includes_checkpoint_if_available(self):
        self.dd.register_agent("agent-a", priority=0)
        self.dd.register_agent("agent-b", priority=3)
        self.dd.save_checkpoint("agent-b", "completed step 3 of pipeline")
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        r = self.dd.resolve_deadlock(dl[0])
        self.assertEqual(r["terminate_agent"], "agent-b")
        self.assertEqual(r["checkpoint"], "completed step 3 of pipeline")

    def test_resolve_no_checkpoint(self):
        self.dd.register_agent("agent-a", priority=0)
        self.dd.register_agent("agent-b", priority=3)
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        r = self.dd.resolve_deadlock(dl[0])
        self.assertEqual(r["terminate_agent"], "agent-b")
        self.assertIsNone(r.get("checkpoint"))

    def test_resolve_unknown_cycle_format(self):
        r = self.dd.resolve_deadlock({"cycle": ["unknown"]})
        self.assertIn("error", r)

    def test_resolve_multiple_cycles_independent(self):
        """Two independent deadlocks, each resolved separately"""
        for a in ["agent-a", "agent-b", "agent-c", "agent-d"]:
            self.dd.register_agent(a)
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        self.dd.add_dependency("agent-c", "agent-d")
        self.dd.add_dependency("agent-d", "agent-c")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 2)
        r1 = self.dd.resolve_deadlock(dl[0])
        r2 = self.dd.resolve_deadlock(dl[1])
        self.assertEqual(r1["suggested"], True)
        self.assertEqual(r2["suggested"], True)
        self.assertNotEqual(r1["terminate_agent"], r2["terminate_agent"])


class TestCheckpoint(unittest.TestCase):
    """Checkpoint 管理"""

    def setUp(self):
        self.dd = DeadlockDetector()

    def test_save_and_get_checkpoint(self):
        self.dd.register_agent("agent-a")
        self.dd.save_checkpoint("agent-a", "completed indexing phase 2")
        cp = self.dd.get_checkpoint("agent-a")
        self.assertEqual(cp, "completed indexing phase 2")

    def test_get_checkpoint_not_set(self):
        self.dd.register_agent("agent-a")
        cp = self.dd.get_checkpoint("agent-a")
        self.assertIsNone(cp)

    def test_get_checkpoint_unregistered_agent(self):
        cp = self.dd.get_checkpoint("unknown")
        self.assertIsNone(cp)

    def test_save_checkpoint_overwrites(self):
        self.dd.register_agent("agent-a")
        self.dd.save_checkpoint("agent-a", "first")
        self.dd.save_checkpoint("agent-a", "second")
        cp = self.dd.get_checkpoint("agent-a")
        self.assertEqual(cp, "second")


class TestGetStatus(unittest.TestCase):
    """状态查询"""

    def setUp(self):
        self.dd = DeadlockDetector()

    def test_get_status_empty(self):
        s = self.dd.get_status()
        self.assertEqual(s, {})

    def test_get_status_single_registered(self):
        self.dd.register_agent("agent-a", priority=1)
        s = self.dd.get_status("agent-a")
        self.assertEqual(s["agent_id"], "agent-a")
        self.assertEqual(s["priority"], 1)

    def test_get_status_unregistered_agent(self):
        s = self.dd.get_status("unknown")
        self.assertIn("error", s)

    def test_get_status_all(self):
        self.dd.register_agent("agent-a", priority=0)
        self.dd.register_agent("agent-b", priority=3)
        self.dd.add_dependency("agent-a", "agent-b")
        s = self.dd.get_status()
        self.assertIn("agent-a", s)
        self.assertIn("agent-b", s)
        self.assertEqual(s["agent-a"]["priority"], 0)
        self.assertEqual(s["agent-b"]["priority"], 3)
        self.assertIn("waiting_for", s["agent-a"])
        self.assertIn("agent-b", s["agent-a"]["waiting_for"])


class TestCrossLayerFeedback(unittest.TestCase):
    """跨层告警"""

    def setUp(self):
        self.dd = DeadlockDetector()

    def test_feedback_received(self):
        r = self.dd.cross_layer_feedback("ecos", "warning", "deadlock risk detected")
        self.assertEqual(r["ok"], True)

    def test_feedback_stored(self):
        self.dd.cross_layer_feedback("ecos", "info", "test message")
        alerts = self.dd.get_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["source"], "ecos")
        self.assertEqual(alerts[0]["severity"], "info")
        self.assertEqual(alerts[0]["message"], "test message")

    def test_feedback_limit(self):
        for i in range(20):
            self.dd.cross_layer_feedback("ecos", "info", f"msg {i}")
        alerts = self.dd.get_alerts(limit=5)
        self.assertEqual(len(alerts), 5)

    def test_feedback_with_severity(self):
        for severity in ["info", "warning", "critical"]:
            self.dd.cross_layer_feedback("kos", severity, "test")
        alerts = self.dd.get_alerts()
        severities = [a["severity"] for a in alerts]
        self.assertIn("info", severities)
        self.assertIn("warning", severities)
        self.assertIn("critical", severities)


class TestMCPTools(unittest.TestCase):
    """MCP 工具定义与处理"""

    def setUp(self):
        self.dd = DeadlockDetector()

    def test_mcp_tools_returns_list(self):
        tools = self.dd.mcp_tools()
        self.assertIsInstance(tools, list)
        self.assertEqual(len(tools), 2)
        names = [t["name"] for t in tools]
        self.assertIn("metaos_deadlock_check", names)
        self.assertIn("metaos_deadlock_resolve", names)

    def test_mcp_handle_deadlock_check(self):
        self.dd.register_agent("agent-a")
        self.dd.register_agent("agent-b")
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        r = self.dd.mcp_handle("metaos_deadlock_check", {})
        self.assertIn("deadlocks", r)
        self.assertIn("timeouts", r)
        self.assertEqual(len(r["deadlocks"]), 1)

    def test_mcp_handle_deadlock_resolve(self):
        self.dd.register_agent("agent-a", priority=0)
        self.dd.register_agent("agent-b", priority=3)
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        r = self.dd.mcp_handle("metaos_deadlock_resolve", {"cycle": dl[0]})
        self.assertEqual(r["suggested"], True)
        self.assertEqual(r["terminate_agent"], "agent-b")

    def test_mcp_handle_unknown_tool(self):
        r = self.dd.mcp_handle("unknown_tool", {})
        self.assertIn("error", r)


class TestIntegrationScenarios(unittest.TestCase):
    """集成场景测试"""

    def setUp(self):
        self.dd = DeadlockDetector()
        for a in ["agent-a", "agent-b", "agent-c"]:
            self.dd.register_agent(a)

    def test_ab_deadlock_detection(self):
        """经典 AB-BA 死锁"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        self.assertIn("agent-a", dl[0]["agents_in_cycle"])
        self.assertIn("agent-b", dl[0]["agents_in_cycle"])

    def test_abc_deadlock_detection(self):
        """A→B→C→A 三节点死锁"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-c")
        self.dd.add_dependency("agent-c", "agent-a")
        dl = self.dd.detect_deadlocks()
        self.assertEqual(len(dl), 1)
        self.assertEqual(len(dl[0]["agents_in_cycle"]), 3)

    def test_detect_release_redetect(self):
        """创建死锁 → 检测 → 释放 → 重新检测 → 无死锁"""
        self.dd.add_dependency("agent-a", "agent-b")
        self.dd.add_dependency("agent-b", "agent-a")
        dl1 = self.dd.detect_deadlocks()
        self.assertEqual(len(dl1), 1)
        self.dd.remove_dependency("agent-b", "agent-a")
        dl2 = self.dd.detect_deadlocks()
        self.assertEqual(dl2, [])

    def test_timeout_and_deadlock_together(self):
        """同时检测超时和死锁"""
        with patch("time.time", return_value=100.0):
            self.dd.register_agent("agent-d")
            self.dd.add_dependency("agent-d", "agent-c")  # D 长时间等待（600s），但不死锁
        with patch("time.time", return_value=100.0 + 590):
            # A-B 死锁在接近检查时间才建立，不会超时
            self.dd.add_dependency("agent-a", "agent-b")
            self.dd.add_dependency("agent-b", "agent-a")
        with patch("time.time", return_value=100.0 + 600):
            dl = self.dd.detect_deadlocks()
            to = self.dd.check_timeouts()
        self.assertEqual(len(dl), 1)
        self.assertEqual(len(to), 1)
        self.assertEqual(to[0]["agent_id"], "agent-d")

    def test_complex_timeline(self):
        """复杂时间线：创建→死锁→解决→恢复正常"""
        with patch("time.time", return_value=100.0):
            self.dd.register_agent("agent-d", priority=0)
            self.dd.add_dependency("agent-a", "agent-b")
            self.dd.add_dependency("agent-b", "agent-c")
            self.dd.add_dependency("agent-c", "agent-a")
            dl1 = self.dd.detect_deadlocks()
            self.assertEqual(len(dl1), 1)
            # Resolve: terminate lowest priority in the cycle
            r = self.dd.resolve_deadlock(dl1[0])
            self.assertEqual(r["suggested"], True)
        # After resolution, remove the cycle
        self.dd.remove_dependency("agent-c", "agent-a")
        dl2 = self.dd.detect_deadlocks()
        self.assertEqual(dl2, [])


if __name__ == "__main__":
    unittest.main()
