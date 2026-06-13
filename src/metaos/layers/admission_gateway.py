"""
MetaOS Admission Gateway - 驾驭工程五大部件准入控制
Implementation for Phase 3 T3.2.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdmissionGateway:
    """
    决策网关准入控制器 (Decision Gateway Admission Controller)
    Enforces the 5 core components of eCOS Governance Engineering for any new domain or agent.
    """

    def __init__(self):
        # 1. 价值观对齐要求
        self.required_values = ["human-centric", "objective", "transparent"]
        # 2. 权限隔离支持的角色
        self.supported_roles = ["generator", "evaluator", "researcher"]

    def evaluate_admission(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Evaluate an incoming agent execution or domain onboarding request.
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
            return {"status": "admitted", "reasons": ["All 5 governance components satisfied."]}
        else:
            logger.warning(f"Admission REJECTED for domain: {domain}. Reasons: {reasons}")
            return {"status": "rejected", "reasons": reasons}
