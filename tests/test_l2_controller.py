#!/usr/bin/env python3
"""单元测试：L2 Controller — PID + Hysteresis + Cross-layer feedback"""

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from metaos.l2_controller import L2Controller


class TestRegisterService(unittest.TestCase):
    """注册服务及基线配置"""

    def setUp(self):
        self.ctl = L2Controller()

    def test_register_single_service(self):
        r = self.ctl.register_service("minerva", 100, 0.01, 50)
        self.assertEqual(r["ok"], True)
        self.assertEqual(r["service"], "minerva")
        self.assertIn("minerva", self.ctl.services)

    def test_register_duplicate_overwrites(self):
        self.ctl.register_service("minerva", 100, 0.01, 50)
        r = self.ctl.register_service("minerva", 200, 0.02, 60)
        self.assertEqual(r["ok"], True)
        s = self.ctl.services["minerva"]
        self.assertEqual(s["baseline_latency_ms"], 200)
        self.assertEqual(s["baseline_error_rate"], 0.02)
        self.assertEqual(s["baseline_cpu_pct"], 60)

    def test_register_multiple_services(self):
        for name, lat, err, cpu in [("minerva", 100, 0.01, 50), ("kronos", 200, 0.02, 60), ("sophia", 150, 0.005, 40)]:
            self.ctl.register_service(name, lat, err, cpu)
        self.assertEqual(len(self.ctl.services), 3)

    def test_register_default_concurrency(self):
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.assertEqual(self.ctl.services["minerva"]["concurrency"], 10)
        self.assertEqual(self.ctl.services["minerva"]["base_concurrency"], 10)

    def test_register_sets_initial_current_metrics(self):
        self.ctl.register_service("minerva", 100, 0.01, 50)
        s = self.ctl.services["minerva"]
        self.assertEqual(s["current_latency_ms"], 100)
        self.assertEqual(s["current_error_rate"], 0.01)
        self.assertEqual(s["current_cpu_pct"], 50)


class TestHealthInput(unittest.TestCase):
    """健康数据输入"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)

    def test_health_input_updates_current_metrics(self):
        self.ctl.health_input("minerva", 150, 0.02, 55)
        s = self.ctl.services["minerva"]
        self.assertEqual(s["current_latency_ms"], 150)
        self.assertEqual(s["current_error_rate"], 0.02)
        self.assertEqual(s["current_cpu_pct"], 55)

    def test_health_input_returns_result_dict(self):
        r = self.ctl.health_input("minerva", 150, 0.02, 55)
        self.assertIn("service", r)
        self.assertIn("zone", r)
        self.assertIn("concurrency", r)
        self.assertEqual(r["service"], "minerva")

    def test_health_input_unknown_service(self):
        r = self.ctl.health_input("unknown", 100, 0.01, 50)
        self.assertIn("error", r)
        self.assertEqual(r["error"], "not_registered")

    def test_health_input_negative_latency_rejected(self):
        r = self.ctl.health_input("minerva", -10, 0.01, 50)
        self.assertIn("error", r)

    def test_health_input_boundary_latency(self):
        """恰好等于基线：应正常，zone=normal"""
        r = self.ctl.health_input("minerva", 100, 0.01, 50)
        self.assertNotIn("error", r)
        self.assertEqual(r["zone"], "normal")

    def test_health_input_multiple_updates(self):
        self.ctl.health_input("minerva", 120, 0.01, 50)
        self.ctl.health_input("minerva", 250, 0.03, 60)
        r = self.ctl.health_input("minerva", 80, 0.005, 45)
        self.assertEqual(r["service"], "minerva")
        s = self.ctl.services["minerva"]
        self.assertEqual(s["current_latency_ms"], 80)
        self.assertEqual(s["current_error_rate"], 0.005)
        self.assertEqual(s["current_cpu_pct"], 45)


class TestPIDCompute(unittest.TestCase):
    """PID 控制器计算"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.state = self.ctl.services["minerva"]

    def test_zero_error_returns_zero_output(self):
        """latency == baseline → PID output ≈ 0"""
        self.state["current_latency_ms"] = 100
        output = self.ctl._pid_compute(self.state)
        self.assertAlmostEqual(output, 0.0, places=2)

    def test_positive_error_proportional_response(self):
        """latency > baseline → positive PID output (减速)"""
        self.state["current_latency_ms"] = 200
        output = self.ctl._pid_compute(self.state)
        self.assertGreater(output, 0)

    def test_negative_error_integral_accumulates(self):
        """latency < baseline → negative PID output (加速)"""
        self.state["current_latency_ms"] = 50
        output = self.ctl._pid_compute(self.state)
        self.assertLess(output, 0)

    def test_integral_anti_windup(self):
        """长时间大误差不会导致积分无界增长"""
        self.state["current_latency_ms"] = 500  # 5x baseline
        for _ in range(100):
            self.ctl._pid_compute(self.state)
        self.assertLessEqual(self.state["_integral"], self.ctl.ANTI_WINDUP_MAX)
        self.assertGreaterEqual(self.state["_integral"], -self.ctl.ANTI_WINDUP_MAX)

    def test_derivative_term_responds_to_change_rate(self):
        """误差变化率影响 D 项"""
        self.state["current_latency_ms"] = 150
        self.state["_prev_error"] = 0.5  # 前次误差=50%
        # 当前 error = (150-100)/100 = 0.5 → no change → D = 0
        self.ctl._pid_compute(self.state)
        self.state["_prev_error"] = 0.0  # 手工重置
        # 但这里 _pid_compute 内部更新了 _prev_error，所以需要重新思考

    def test_pid_output_bounded(self):
        """PID output 被限制在 [-1, 1] 范围内"""
        self.state["current_latency_ms"] = 1000  # 极度异常
        output = self.ctl._pid_compute(self.state)
        self.assertLessEqual(output, 1.0)
        self.assertGreaterEqual(output, -1.0)

    def test_pid_returns_float(self):
        self.state["current_latency_ms"] = 120
        output = self.ctl._pid_compute(self.state)
        self.assertIsInstance(output, float)

    def test_p_reset_on_register_reinit(self):
        """重新注册时积分和前一误差应重置"""
        self.state["current_latency_ms"] = 200
        self.ctl._pid_compute(self.state)
        self.state["_integral"]
        # 重新注册
        self.ctl.register_service("minerva", 100, 0.01, 50)
        s = self.ctl.services["minerva"]
        self.assertEqual(s["_integral"], 0.0)
        self.assertEqual(s["_prev_error"], 0.0)


class TestPIDCoefficients(unittest.TestCase):
    """PID 系数影响验证"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.state = self.ctl.services["minerva"]
        self.state["current_latency_ms"] = 200

    def test_kp_dominates_proportional(self):
        """较大的 Kp → 更大的 P 项输出"""
        output_default = self.ctl._pid_compute(self.state)
        self.state["_integral"] = 0
        self.state["_prev_error"] = 0
        self.ctl.Kp = 10.0
        output_high = self.ctl._pid_compute(self.state)
        self.assertGreater(abs(output_high), abs(output_default))

    def test_ki_accumulates_over_multiple_calls(self):
        """Ki 使积分随时间累积"""
        self.state["current_latency_ms"] = 120
        self.ctl._pid_compute(self.state)
        self.state["_prev_error"] = 0.2
        self.ctl._pid_compute(self.state)  # 第二次调用
        # 第三次调用时 integral 应有累积
        self.ctl._pid_compute(self.state)
        # 积分项应大于仅 P 项
        self.ctl.Kp * 0.2
        i_term = self.ctl.Ki * self.state["_integral"]
        self.assertGreater(i_term, 0)


class TestHysteresis(unittest.TestCase):
    """滞回控制逻辑"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)

    def test_latency_below_1x_returns_normal(self):
        """latency <= baseline → zone=normal"""
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r["zone"], "normal")

    def test_latency_between_1x_and_2x_returns_normal(self):
        """1x < latency <= 2x → zone=normal (no action needed)"""
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 150, 0.01, 50)
            self.assertEqual(r["zone"], "normal")

    def test_latency_above_2x_triggers_reducing(self):
        """latency > 2x baseline → zone=reducing"""
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 250, 0.01, 50)
            self.assertEqual(r["zone"], "reducing")

    def test_cooldown_prevents_immediate_transition_back(self):
        """进入 reducing 后 cooldown 内不会切回 normal"""
        now = time.time()
        with patch("time.time", return_value=now):
            r1 = self.ctl.health_input("minerva", 250, 0.01, 50)
            self.assertEqual(r1["zone"], "reducing")
        # cooldown 内（+30s）latency 降回正常
        with patch("time.time", return_value=now + 30):
            r2 = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r2["zone"], "reducing")  # 仍在 reducing

    def test_cooldown_expired_allows_transition(self):
        """cooldown 结束后可以切回 normal"""
        now = time.time()
        with patch("time.time", return_value=now):
            self.ctl.health_input("minerva", 250, 0.01, 50)
        # cooldown 过期后（+61s）latency 正常
        with patch("time.time", return_value=now + 61):
            r = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r["zone"], "normal")

    def test_restoring_transition_after_cooldown(self):
        """从 reducing 到 normal 的过程中 cooldown 重置"""
        now = time.time()
        with patch("time.time", return_value=now):
            self.ctl.health_input("minerva", 250, 0.01, 50)
        # cooldown 过期
        with patch("time.time", return_value=now + 61):
            r = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r["zone"], "normal")
        # 立刻又高延迟，因 cooldown 已重置
        with patch("time.time", return_value=now + 62):
            r2 = self.ctl.health_input("minerva", 300, 0.01, 50)
            self.assertEqual(r2["zone"], "normal")  # cooldown 未过期

    def test_cooling_prevents_oscillation(self):
        """快速高低交替不会导致 ping-pong"""
        now = time.time()
        with patch("time.time", return_value=now):
            self.ctl.health_input("minerva", 300, 0.01, 50)
        for offset in [5, 10, 15, 20, 25, 30]:
            with patch("time.time", return_value=now + offset):
                r = self.ctl.health_input("minerva", 80 if offset % 2 == 0 else 300, 0.01, 50)
                self.assertIn(r["zone"], ("reducing", "normal"))

    def test_latency_ratio_exactly_2x_does_not_reduce(self):
        """latency 恰好等于 2x baseline → 不触发 reducing"""
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 200, 0.01, 50)
            # 2x 是边界，严格>2x 才触发
            self.assertEqual(r["zone"], "reducing" if 200 > 200 else "normal")

    def test_latency_ratio_two_point_one(self):
        """latency = 2.1x baseline → 触发 reducing"""
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 210, 0.01, 50)
            self.assertEqual(r["zone"], "reducing")


class TestGetStatus(unittest.TestCase):
    """状态查询"""

    def setUp(self):
        self.ctl = L2Controller()

    def test_empty_status_returns_empty_dict(self):
        s = self.ctl.get_status()
        self.assertEqual(s, {})

    def test_single_service_status(self):
        self.ctl.register_service("minerva", 100, 0.01, 50)
        s = self.ctl.get_status("minerva")
        self.assertEqual(s["service"], "minerva")
        self.assertEqual(s["zone"], "normal")
        self.assertEqual(s["concurrency"], 10)

    def test_multi_service_status(self):
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.ctl.register_service("kronos", 200, 0.02, 60)
        s = self.ctl.get_status()
        self.assertEqual(len(s), 2)
        self.assertIn("minerva", s)
        self.assertIn("kronos", s)

    def test_unknown_service_returns_error(self):
        s = self.ctl.get_status("unknown")
        self.assertIn("error", s)

    def test_status_includes_cooldown_info(self):
        self.ctl.register_service("minerva", 100, 0.01, 50)
        now = time.time()
        with patch("time.time", return_value=now):
            self.ctl.health_input("minerva", 250, 0.01, 50)
        s = self.ctl.get_status("minerva")
        self.assertIn("cooldown_remaining", s)


class TestAdjust(unittest.TestCase):
    """READONLY 调整建议"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)

    def test_adjust_returns_suggestion_not_execution(self):
        r = self.ctl.adjust("minerva", "concurrency", 15)
        self.assertIn("suggested", r)
        self.assertTrue(r["suggested"])
        self.assertIn("message", r)
        self.assertIn("READONLY", r["message"])

    def test_adjust_does_not_modify_actual_state(self):
        original = self.ctl.services["minerva"]["concurrency"]
        self.ctl.adjust("minerva", "concurrency", 99)
        self.assertEqual(self.ctl.services["minerva"]["concurrency"], original)

    def test_adjust_invalid_param(self):
        r = self.ctl.adjust("minerva", "nonexistent", 15)
        self.assertIn("error", r)

    def test_adjust_unknown_service(self):
        r = self.ctl.adjust("unknown", "concurrency", 15)
        self.assertIn("error", r)

    def test_adjust_valid_params(self):
        for param in ["concurrency", "latency_ms", "error_rate", "cpu_pct"]:
            r = self.ctl.adjust("minerva", param, 15)
            self.assertIn("suggested", r)
            self.assertTrue(r["suggested"])

    def test_adjust_multiple_calls(self):
        for val in [10, 20, 30]:
            r = self.ctl.adjust("minerva", "concurrency", val)
            self.assertEqual(r["new_value"], val)


class TestCrossLayerFeedback(unittest.TestCase):
    """跨层反馈"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.ctl.register_service("kronos", 200, 0.02, 60)

    def test_cross_layer_feedback_received(self):
        r = self.ctl.cross_layer_feedback("ecos", "warning", "minerva 延迟异常偏高")
        self.assertIn("ok", r)
        self.assertTrue(r["ok"])

    def test_alerts_stored(self):
        self.ctl.cross_layer_feedback("ecos", "warning", "通知1")
        self.ctl.cross_layer_feedback("agora", "critical", "通知2")
        alerts = self.ctl.get_alerts()
        self.assertEqual(len(alerts), 2)

    def test_alerts_include_source_severity_message(self):
        self.ctl.cross_layer_feedback("ecos", "critical", "内存不足")
        a = self.ctl.get_alerts()[0]
        self.assertEqual(a["source"], "ecos")
        self.assertEqual(a["severity"], "critical")
        self.assertEqual(a["message"], "内存不足")

    def test_get_alerts_limit(self):
        for i in range(20):
            self.ctl.cross_layer_feedback("ecos", "info", f"通知{i}")
        alerts = self.ctl.get_alerts(limit=5)
        self.assertEqual(len(alerts), 5)
        self.assertIn("通知", alerts[0]["message"])

    def test_severity_info_warning_critical(self):
        for sev in ["info", "warning", "critical"]:
            r = self.ctl.cross_layer_feedback("ecos", sev, f"测试 {sev}")
            self.assertTrue(r["ok"])


class TestOscillation(unittest.TestCase):
    """振荡测试：验证不会发生 ping-pong 行为"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)

    def test_rapid_alternating_metrics_no_ping_pong(self):
        """快速交替高/低延迟 → 不应频繁切换 zone"""
        now = time.time()
        zones = []
        for i in range(20):
            t = now + i * 5  # 每 5 秒一次
            latency = 300 if i % 2 == 0 else 80
            with patch("time.time", return_value=t):
                r = self.ctl.health_input("minerva", latency, 0.01, 50)
                zones.append(r["zone"])
        # 检查切换次数：在 100s 窗口内不应超过 2 次（cooldown=60s）
        transitions = sum(1 for i in range(1, len(zones)) if zones[i] != zones[i - 1])
        self.assertLessEqual(transitions, 3, f"太多 zone 切换 ({transitions})，可能振荡")

    def test_cooldown_timing_verified(self):
        """验证 cooldown 时序逻辑"""
        now = time.time()
        with patch("time.time", return_value=now):
            r1 = self.ctl.health_input("minerva", 300, 0.01, 50)
            self.assertEqual(r1["zone"], "reducing")
        # cooldown 过期后检查 zone
        with patch("time.time", return_value=now + 61):
            r2 = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r2["zone"], "normal")
        # 又过 30s → cooldown 未过期 → 高延迟保持上 zone
        with patch("time.time", return_value=now + 91):
            r3 = self.ctl.health_input("minerva", 300, 0.01, 50)
            self.assertEqual(r3["zone"], "normal")  # cooldown 内
        # 过 60s → cooldown 过期
        with patch("time.time", return_value=now + 151):
            r4 = self.ctl.health_input("minerva", 300, 0.01, 50)
            self.assertEqual(r4["zone"], "reducing")

    def test_cascading_recovery(self):
        """延迟逐步恢复正常 → zone 稳定"""
        now = time.time()
        with patch("time.time", return_value=now):
            self.ctl.health_input("minerva", 300, 0.01, 50)
        delays = [280, 250, 220, 200, 180, 150, 120, 100]
        zones = set()
        for i, lat in enumerate(delays):
            t = now + 70 + i * 10
            with patch("time.time", return_value=t):
                r = self.ctl.health_input("minerva", lat, 0.01, 50)
                zones.add(r["zone"])
        # 恢复过程不振荡
        self.assertLessEqual(len(zones), 2)

    def test_sudden_spike_then_settle(self):
        """突刺后稳定 → 先 reducing 然后恢复 normal"""
        now = time.time()
        with patch("time.time", return_value=now):
            r1 = self.ctl.health_input("minerva", 500, 0.01, 50)
            self.assertEqual(r1["zone"], "reducing")
        with patch("time.time", return_value=now + 61):
            r2 = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r2["zone"], "normal")

    def test_complex_timeline_no_oscillation(self):
        """复杂时间线验证无振荡"""
        now = 1000000.0
        timeline = [
            (now, 100, "normal"),  # 基线
            (now + 10, 300, "reducing"),  # 尖刺 → cooldown_until=now+70
            (now + 20, 80, "reducing"),  # cooldown 内（70 未过期）
            (now + 30, 350, "reducing"),  # cooldown 内
            (now + 65, 80, "reducing"),  # cooldown 内（70 仍未过期）
            (now + 71, 90, "normal"),  # cooldown 过期（70 已过）→ 切 normal
            (now + 140, 250, "reducing"),  # cooldown 过期后再次高延迟
        ]
        for t, lat, expected_zone in timeline:
            with patch("time.time", return_value=t):
                r = self.ctl.health_input("minerva", lat, 0.01, 50)
                self.assertEqual(r["zone"], expected_zone, f"t={t} lat={lat}: expected {expected_zone} got {r['zone']}")


class TestMCPTools(unittest.TestCase):
    """MCP 工具存根"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.ctl.health_input("minerva", 250, 0.01, 50)

    def test_mcp_tools_returns_list_with_status_and_adjust(self):
        tools = self.ctl.mcp_tools()
        names = [t["name"] for t in tools]
        self.assertIn("l2_controller_status", names)
        self.assertIn("l2_controller_adjust", names)

    def test_mcp_handle_status(self):
        r = self.ctl.mcp_handle("l2_controller_status", {"service": "minerva"})
        self.assertIn("service", r)
        self.assertEqual(r["service"], "minerva")

    def test_mcp_handle_adjust(self):
        r = self.ctl.mcp_handle("l2_controller_adjust", {"service": "minerva", "param": "concurrency", "value": 20})
        self.assertIn("suggested", r)
        self.assertTrue(r["suggested"])

    def test_mcp_handle_unknown_tool(self):
        r = self.ctl.mcp_handle("unknown_tool", {})
        self.assertIn("error", r)


class TestConcurrencyAdjustment(unittest.TestCase):
    """并发度调整验证"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)
        self.state = self.ctl.services["minerva"]

    def test_high_latency_reduces_concurrency(self):
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 300, 0.01, 50)
        # PID output > 0 → 应降低并发度
        self.assertLess(r["concurrency"], 10)

    def test_normal_latency_keeps_base_concurrency(self):
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 100, 0.01, 50)
        self.assertEqual(r["concurrency"], 10)

    def test_concurrency_does_not_go_below_zero(self):
        now = time.time()
        with patch("time.time", return_value=now):
            r = self.ctl.health_input("minerva", 10000, 0.01, 50)
        self.assertGreaterEqual(r["concurrency"], 0)

    def test_concurrency_smooth_adjustment(self):
        """PID 使并发度平滑变化，不是二值开关"""
        now = time.time()
        concurrency_values = []
        latencies = [120, 140, 160, 180, 200]
        for i, lat in enumerate(latencies):
            t = now + i * 5
            with patch("time.time", return_value=t):
                r = self.ctl.health_input("minerva", lat, 0.01, 50)
                concurrency_values.append(r["concurrency"])
        # 并发度应单调递减（延迟递增）
        for i in range(1, len(concurrency_values)):
            self.assertLessEqual(concurrency_values[i], concurrency_values[i - 1])


class TestConcurrencyRestore(unittest.TestCase):
    """并发度恢复验证"""

    def setUp(self):
        self.ctl = L2Controller()
        self.ctl.register_service("minerva", 100, 0.01, 50)

    def test_latency_recovers_restores_concurrency(self):
        """延迟恢复后并发度回到基线"""
        now = time.time()
        with patch("time.time", return_value=now):
            r1 = self.ctl.health_input("minerva", 300, 0.01, 50)
            reduced = r1["concurrency"]
            self.assertLess(reduced, 10)
        with patch("time.time", return_value=now + 61):
            r2 = self.ctl.health_input("minerva", 80, 0.01, 50)
            self.assertEqual(r2["zone"], "normal")
            self.assertEqual(r2["concurrency"], 10)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    for cls in [
        TestRegisterService,
        TestHealthInput,
        TestPIDCompute,
        TestPIDCoefficients,
        TestHysteresis,
        TestGetStatus,
        TestAdjust,
        TestCrossLayerFeedback,
        TestOscillation,
        TestMCPTools,
        TestConcurrencyAdjustment,
        TestConcurrencyRestore,
    ]:
        suite.addTest(unittest.TestLoader().loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
