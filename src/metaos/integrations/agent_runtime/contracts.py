"""Canonical contracts shared by MetaOS and provider adapters.

Operational risk, execution mode, and dynamic gate result are deliberately
separate concepts:

* risk class describes the inherent impact of the requested operation;
* execution mode limits what the adapter may attempt;
* gate decision is MetaOS's runtime authorization outcome for this session.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class OperationalRisk(StrEnum):
    R0 = "R0"  # answer/text only
    R1 = "R1"  # read-only external or local information
    R2 = "R2"  # reversible local staged change
    R3 = "R3"  # external write, sensitive data, account action
    R4 = "R4"  # irreversible or high-impact action


class ExecutionMode(StrEnum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    STAGE = "stage"
    COMMIT = "commit"


class ProviderKind(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    GENERIC = "generic"


class SessionStatus(StrEnum):
    PREPARED = "prepared"
    BLOCKED = "blocked"
    RUNNING = "running"
    FINALIZED = "finalized"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class VerificationPlan:
    commands: list[str] = field(default_factory=list)
    expected_outcomes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class CapabilityRequest:
    profile: str = "core"
    requested: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)


@dataclass
class AgentSession:
    """The provider-neutral session contract persisted as a MetaOS asset.

    The contract intentionally contains no secret material and is safe to
    export only according to its asset access level.
    """

    session_id: str = field(default_factory=lambda: f"agent-{uuid4().hex[:16]}")
    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    h_id: str = ""
    provider: ProviderKind = ProviderKind.GENERIC
    description: str = ""
    risk: OperationalRisk = OperationalRisk.R0
    mode: ExecutionMode = ExecutionMode.OBSERVE
    gate_decision: str = "green"
    gate_reason: str = ""
    capability: CapabilityRequest = field(default_factory=CapabilityRequest)
    scope: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    verification: VerificationPlan = field(default_factory=VerificationPlan)
    rollback_or_containment: list[str] = field(default_factory=list)
    status: SessionStatus = SessionStatus.PREPARED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finalized_at: datetime | None = None
    result_summary: str = ""
    evidence: list[str] = field(default_factory=list)
    decision_id: str = ""
    asset_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provider"] = self.provider.value
        data["risk"] = self.risk.value
        data["mode"] = self.mode.value
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["finalized_at"] = self.finalized_at.isoformat() if self.finalized_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSession":
        verification = data.get("verification") or {}
        capability = data.get("capability") or {}
        created_at = data.get("created_at")
        finalized_at = data.get("finalized_at")
        return cls(
            session_id=data.get("session_id") or f"agent-{uuid4().hex[:16]}",
            task_id=data.get("task_id") or uuid4().hex[:12],
            h_id=data.get("h_id", ""),
            provider=ProviderKind(data.get("provider", ProviderKind.GENERIC.value)),
            description=data.get("description", ""),
            risk=OperationalRisk(data.get("risk", OperationalRisk.R0.value)),
            mode=ExecutionMode(data.get("mode", ExecutionMode.OBSERVE.value)),
            gate_decision=data.get("gate_decision", "green"),
            gate_reason=data.get("gate_reason", ""),
            capability=CapabilityRequest(**capability),
            scope=list(data.get("scope") or []),
            exclusions=list(data.get("exclusions") or []),
            success_criteria=list(data.get("success_criteria") or []),
            stop_conditions=list(data.get("stop_conditions") or []),
            verification=VerificationPlan(**verification),
            rollback_or_containment=list(data.get("rollback_or_containment") or []),
            status=SessionStatus(data.get("status", SessionStatus.PREPARED.value)),
            created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(UTC),
            finalized_at=datetime.fromisoformat(finalized_at) if finalized_at else None,
            result_summary=data.get("result_summary", ""),
            evidence=list(data.get("evidence") or []),
            decision_id=data.get("decision_id", ""),
            asset_id=data.get("asset_id", ""),
        )


def validate_session_policy(session: AgentSession) -> list[str]:
    """Return policy violations without making an execution decision."""
    violations: list[str] = []
    if session.risk in {OperationalRisk.R3, OperationalRisk.R4} and session.mode != ExecutionMode.COMMIT:
        violations.append("R3/R4 sessions must use commit mode only after explicit authorization.")
    if session.mode == ExecutionMode.COMMIT and not session.success_criteria:
        violations.append("commit mode requires explicit success criteria.")
    if session.mode == ExecutionMode.COMMIT and not session.verification.expected_outcomes:
        violations.append("commit mode requires a verification plan.")
    if session.risk == OperationalRisk.R4 and not session.rollback_or_containment:
        violations.append("R4 sessions require rollback or containment instructions.")
    return violations
