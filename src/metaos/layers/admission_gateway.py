"""
MetaOS Admission Gateway - 驾驭工程五大部件准入控制
Implementation for Phase 3 T3.2.

ADR-0252 O-D4: default mode is **observe** (2-week observation window).
Set METAOS_ADMIT_MODE=blocking to hard-reject. informational-only is gone.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ADR-0252 O-D4: observe (default) | blocking
_DEFAULT_MODE = "observe"


class AdmissionGateway:
    """
    决策网关准入控制器 (Decision Gateway Admission Controller)
    Enforces the 5 core components of eCOS Governance Engineering for any new domain or agent.
    """

    def __init__(self, mode: str | None = None):
        # 1. 价值观对齐要求
        self.required_values = ["human-centric", "objective", "transparent"]
        # 2. 权限隔离支持的角色
        self.supported_roles = ["generator", "evaluator", "researcher"]
        raw = (mode or os.environ.get("METAOS_ADMIT_MODE") or _DEFAULT_MODE).lower()
        self.mode = raw if raw in {"observe", "blocking"} else _DEFAULT_MODE

    def evaluate_admission(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Evaluate an incoming agent execution or domain onboarding request.

        mode=observe (default): violations return admitted_with_warnings (log + reasons),
        still allow pass-through so mis-block data can be collected.
        mode=blocking: violations return rejected.
        """
        domain = request.get("domain", "unknown")
        agent_role = request.get("role", "unknown")
        capabilities = request.get("capabilities", [])

        reasons: list[str] = []
        is_admitted = True

        # 1. 价值观对齐 (Value Alignment)
        declared_values = request.get("declared_values", [])
        missing_values = [v for v in self.required_values if v not in declared_values]
        if missing_values:
            is_admitted = False
            reasons.append(f"[C1 Value Alignment] Missing required values: {missing_values}")

        # 2. 权限隔离 (Permission Isolation)
        if agent_role not in self.supported_roles:
            is_admitted = False
            reasons.append(
                f"[C2 Permission Isolation] Invalid or missing execution role: "
                f"'{agent_role}'. Must be one of {self.supported_roles}"
            )

        # 3. 过程监督 (Process Monitoring)
        if not request.get("supports_otlp", False):
            is_admitted = False
            reasons.append("[C3 Process Monitoring] Agent does not declare support for OTLP tracing.")

        # 4. 可回溯性 (Traceability/Auditability)
        if not request.get("omo_audit_trail_id"):
            is_admitted = False
            reasons.append("[C4 Traceability] Missing 'omo_audit_trail_id' for accountability.")

        # 5. 应急熔断 (Emergency Kill-switch)
        if "disable_kill_switch" in capabilities or "bypass_sandbox" in capabilities:
            is_admitted = False
            reasons.append("[C5 Circuit Breaker] Agent requests to bypass sandbox or disable kill-switch. REJECTED.")

        if is_admitted:
            logger.info(f"Admission GRANTED for domain: {domain}, role: {agent_role}")
            return {
                "status": "admitted",
                "mode": self.mode,
                "reasons": ["All 5 governance components satisfied."],
            }

        if self.mode == "observe":
            logger.warning(
                "Admission OBSERVE (would reject) for domain=%s mode=%s reasons=%s",
                domain,
                self.mode,
                reasons,
            )
            return {
                "status": "admitted_with_warnings",
                "mode": "observe",
                "reasons": reasons,
                "would_reject": True,
            }

        logger.warning(f"Admission REJECTED for domain: {domain}. Reasons: {reasons}")
        return {"status": "rejected", "mode": "blocking", "reasons": reasons}
