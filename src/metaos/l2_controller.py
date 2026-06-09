"""L2 Controller — PID + Hysteresis for capability layer (READONLY prototype)"""

from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

READONLY_MSG = "READONLY: requires human confirmation — simulation only, no production effect"


class L2Controller:
    """L2 capability layer controller with PID smooth adjustment and hysteresis.

    READONLY — all adjustments are suggestions only, not executed.
    """

    Kp = 0.5  # Proportional coefficient
    Ki = 0.1  # Integral coefficient
    Kd = 0.2  # Derivative coefficient
    HYSTERESIS_COOLDOWN = 60  # seconds
    HIGH_THRESHOLD = 2.0  # latency > 2x baseline → reduce
    LOW_THRESHOLD = 1.0  # latency < 1x baseline → restore
    ANTI_WINDUP_MAX = 100.0  # integral anti-windup limit
    DEFAULT_CONCURRENCY = 10  # default base concurrency
    VALID_PARAMS = frozenset({"concurrency", "latency_ms", "error_rate", "cpu_pct"})

    def __init__(self):
        self.services: dict[str, dict[str, Any]] = {}
        self._alerts: list[dict[str, Any]] = []

    # ── Service Registration ──

    def register_service(
        self,
        name: str,
        baseline_latency_ms: float = 100,
        baseline_error_rate: float = 0.01,
        baseline_cpu_pct: float = 50,
    ) -> dict:
        """Register an L2 service with baseline health metrics."""
        self.services[name] = {
            "baseline_latency_ms": baseline_latency_ms,
            "baseline_error_rate": baseline_error_rate,
            "baseline_cpu_pct": baseline_cpu_pct,
            "current_latency_ms": baseline_latency_ms,
            "current_error_rate": baseline_error_rate,
            "current_cpu_pct": baseline_cpu_pct,
            "concurrency": self.DEFAULT_CONCURRENCY,
            "base_concurrency": self.DEFAULT_CONCURRENCY,
            "zone": "normal",
            "cooldown_until": 0.0,
            "_integral": 0.0,
            "_prev_error": 0.0,
            "_last_pid_time": 0.0,
        }
        return {"ok": True, "service": name}

    # ── Health Input ──

    def health_input(
        self,
        service: str,
        latency_ms: float,
        error_rate: float,
        cpu_pct: float,
    ) -> dict:
        """Receive a health report for an L2 service.

        Returns current status including zone and recommended concurrency.
        """
        state = self.services.get(service)
        if state is None:
            return {"error": "not_registered"}
        if latency_ms < 0:
            return {"error": "negative_latency"}

        # Update current metrics
        state["current_latency_ms"] = latency_ms
        state["current_error_rate"] = error_rate
        state["current_cpu_pct"] = cpu_pct

        # Compute PID and hysteresis
        pid_output = self._pid_compute(state)
        zone = self._check_hysteresis(state, pid_output)

        # Apply adjustment (simulated)
        new_concurrency = state["concurrency"]
        if zone == "reducing":
            # Clamp pid_output to [0, 1] for reduction factor
            reduction = max(0.0, min(1.0, pid_output))
            new_concurrency = max(0, int(state["base_concurrency"] * (1.0 - reduction)))
            _log.info("L0 SSB: Signaling reduction for %s to %d concurrency", service, new_concurrency)
        else:
            new_concurrency = state["base_concurrency"]

        state["concurrency"] = new_concurrency

        if zone != "normal":
            # 强制将重大决断写入 L0 SSB Immutable Log (X1 侧链锚定)
            try:
                import httpx

                httpx.post(
                    "http://127.0.0.1:8080/v1/tools/call",
                    json={
                        "name": "append_ssb_log",
                        "arguments": {
                            "event_type": "L2_CIRCUIT_BREAK",
                            "agent_name": "metaos.l2_controller",
                            "summary": f"L2 Controller shifted {service} to {zone} zone",
                            "detail": f"New concurrency: {new_concurrency}, latency: {latency_ms}ms",
                        },
                    },
                    timeout=1.0,
                )
            except Exception as e:
                _log.warning("Failed to anchor L2 circuit breaking to L0 SSB", exc_info=e)

        return {
            "ok": True,
            "service": service,
            "zone": zone,
            "concurrency": new_concurrency,
            "status": READONLY_MSG if zone != "normal" else "normal",
        }

    # ── PID Controller ──

    def _pid_compute(self, state: dict) -> float:
        """Compute PID output. Returns value in [-1, 1].

        Positive → service is slow (error > 0), reduce concurrency.
        Negative → service is fast (error < 0), can increase concurrency.
        """
        now = time.time()
        current = state["current_latency_ms"]
        baseline = state["baseline_latency_ms"]
        error = (current - baseline) / baseline if baseline else 0.0

        dt = now - state["_last_pid_time"] if state["_last_pid_time"] > 0 else 0.1
        if dt <= 0:
            dt = 0.1

        # P — proportional
        p_term = self.Kp * error

        # I — integral with anti-windup
        state["_integral"] += error * dt
        state["_integral"] = max(-self.ANTI_WINDUP_MAX, min(self.ANTI_WINDUP_MAX, state["_integral"]))
        i_term = self.Ki * state["_integral"]

        # D — derivative (skip on first call, no history)
        if state["_last_pid_time"] > 0:
            d_term = self.Kd * (error - state["_prev_error"]) / dt
        else:
            d_term = 0.0

        # Combine and clamp
        output = p_term + i_term + d_term
        output = max(-1.0, min(1.0, output))

        # Update state for next call
        state["_prev_error"] = error
        state["_last_pid_time"] = now

        return output

    # ── Hysteresis ──

    def _check_hysteresis(self, state: dict, pid_output: float) -> str:
        """Apply hysteresis rules with cooldown. Returns zone name."""
        now = time.time()
        ratio = state["current_latency_ms"] / state["baseline_latency_ms"] if state["baseline_latency_ms"] else 1.0

        # Determine desired zone based on ratio
        if ratio > self.HIGH_THRESHOLD:
            desired = "reducing"
        elif ratio < self.LOW_THRESHOLD:
            desired = "normal"
        else:
            # Between 1x-2x: stay in current zone (hysteresis band)
            desired = state["zone"]

        # Cooldown gate: only transition if cooldown has expired
        if desired != state["zone"] and now >= state["cooldown_until"]:
            state["zone"] = desired
            state["cooldown_until"] = now + self.HYSTERESIS_COOLDOWN

        return state["zone"]

    # ── Status Query ──

    def get_status(self, service: str | None = None) -> dict:
        """Return status for one or all services."""
        if service:
            state = self.services.get(service)
            if state is None:
                return {"error": "not_registered"}
            cooldown_remaining = max(0.0, state["cooldown_until"] - time.time())
            return {
                "service": service,
                "zone": state["zone"],
                "concurrency": state["concurrency"],
                "base_concurrency": state["base_concurrency"],
                "current_latency_ms": state["current_latency_ms"],
                "current_error_rate": state["current_error_rate"],
                "current_cpu_pct": state["current_cpu_pct"],
                "baseline_latency_ms": state["baseline_latency_ms"],
                "cooldown_remaining": round(cooldown_remaining, 1),
            }

        # Return all services
        result = {}
        for name in self.services:
            result[name] = self.get_status(name)
        return result

    # ── READONLY Adjust ──

    def adjust(self, service: str, param: str, value: Any) -> dict:
        """Suggest an adjustment (READONLY — no actual change).

        Returns a suggestion dict; the system does not execute it.
        """
        state = self.services.get(service)
        if state is None:
            return {"error": "not_registered"}
        if param not in self.VALID_PARAMS:
            return {"error": f"invalid_param: {param}"}

        # Map param to the actual state key for display
        param_map = {
            "concurrency": "concurrency",
            "latency_ms": "current_latency_ms",
            "error_rate": "current_error_rate",
            "cpu_pct": "current_cpu_pct",
        }
        current_val = state.get(param_map[param], "?")
        return {
            "suggested": True,
            "service": service,
            "param": param,
            "old_value": current_val,
            "new_value": value,
            "message": READONLY_MSG,
        }

    # ── Cross-layer Feedback ──

    def cross_layer_feedback(self, source: str, severity: str, message: str) -> dict:
        """Receive health alert from another layer (ecos, agora, etc.)."""
        self._alerts.append(
            {
                "source": source,
                "severity": severity,
                "message": message,
                "timestamp": time.time(),
            }
        )
        _log.info("Cross-layer feedback from %s [%s]: %s", source, severity, message)
        return {"ok": True}

    def get_alerts(self, limit: int = 10) -> list[dict]:
        """Return recent cross-layer alerts, newest first."""
        return list(reversed(self._alerts))[:limit]

    # ── MCP Tools (stub) ──

    @staticmethod
    def mcp_tools() -> list[dict]:
        """Return MCP tool definitions."""
        return [
            {
                "name": "l2_controller_status",
                "description": "L2 控制器状态 — 查询服务健康状况和当前 zone",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "服务名称 (可选，不传返回全部)",
                            "default": "",
                        },
                    },
                },
            },
            {
                "name": "l2_controller_adjust",
                "description": "L2 控制器调整建议 — READONLY，仅返回建议",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string"},
                        "param": {
                            "type": "string",
                            "enum": ["concurrency", "latency_ms", "error_rate", "cpu_pct"],
                        },
                        "value": {"type": "number"},
                    },
                    "required": ["service", "param", "value"],
                },
            },
        ]

    def mcp_handle(self, tool_name: str, params: dict) -> dict:
        """Handle MCP tool calls."""
        if tool_name == "l2_controller_status":
            return self.get_status(params.get("service", "") or None)
        elif tool_name == "l2_controller_adjust":
            return self.adjust(
                params["service"],
                params["param"],
                params["value"],
            )
        return {"error": f"unknown_tool: {tool_name}"}
