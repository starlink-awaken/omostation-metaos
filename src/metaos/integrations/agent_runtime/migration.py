"""Migration helpers for legacy provider task-envelope files."""

from __future__ import annotations

from typing import Any

from .contracts import (
    AgentSession,
    CapabilityRequest,
    ExecutionMode,
    OperationalRisk,
    ProviderKind,
    VerificationPlan,
)


def session_from_legacy_envelope(
    payload: dict[str, Any], provider: ProviderKind = ProviderKind.GENERIC
) -> AgentSession:
    """Convert a v0.1 AgentKit envelope into the canonical session contract.

    This is intentionally a one-way compatibility bridge. Canonical sessions
    must not be downgraded into a second source of truth.
    """
    return AgentSession(
        task_id=payload.get("task_id") or payload.get("id") or "",
        h_id=payload.get("h_id", ""),
        provider=provider,
        description=payload.get("description") or payload.get("objective") or "",
        risk=OperationalRisk(payload.get("risk", OperationalRisk.R0.value)),
        mode=ExecutionMode(payload.get("mode", ExecutionMode.OBSERVE.value)),
        capability=CapabilityRequest(profile=payload.get("capability_profile", "core")),
        scope=list(payload.get("scope") or []),
        exclusions=list(payload.get("exclusions") or []),
        success_criteria=list(payload.get("success_criteria") or []),
        stop_conditions=list(payload.get("stop_conditions") or []),
        verification=VerificationPlan(
            commands=list(payload.get("verification_plan") or []),
            expected_outcomes=list(payload.get("verification_expected_outcomes") or []),
        ),
        rollback_or_containment=list(payload.get("rollback_or_containment") or []),
    )
