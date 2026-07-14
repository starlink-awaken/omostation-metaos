"""Canonical contracts shared by MetaOS and provider adapters.

Operational risk, execution mode, dynamic gate result, and human confirmation
are deliberately separate concepts:

* risk class describes the inherent impact of the requested operation;
* execution mode limits what the adapter may attempt;
* gate decision is MetaOS's runtime authorization outcome for this session;
* confirmation records the human response required by a yellow gate.
"""

from __future__ import annotations

import hashlib
import json
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


class ConfirmationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class VerificationPlan:
    commands: list[str] = field(default_factory=list)
    expected_outcomes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class CapabilityRequest:
    # Empty means the runtime derives a profile from risk and mode.
    profile: str = ""
    requested: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)


@dataclass
class TargetBinding:
    """A concrete high-impact operation approved for one short-lived session."""

    kind: str = ""
    target: str = ""
    operation: str = ""
    scope: list[str] = field(default_factory=list)
    expires_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = {
            "kind": self.kind,
            "target": self.target,
            "operation": self.operation,
            "scope": sorted(self.scope),
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def is_expired(self, now: datetime | None = None) -> bool:
        if not self.expires_at:
            return True
        try:
            expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry <= (now or datetime.now(UTC))


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
    confirmation_status: ConfirmationStatus = ConfirmationStatus.NOT_REQUIRED
    capability: CapabilityRequest = field(default_factory=CapabilityRequest)
    target_binding: TargetBinding | None = None
    approved_target_fingerprint: str = ""
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
    evidence_bundle: dict[str, Any] = field(default_factory=dict)
    decision_id: str = ""
    asset_id: str = ""
    integrity_hmac: str = ""  # Phase D content HMAC (signature only)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provider"] = self.provider.value
        data["risk"] = self.risk.value
        data["mode"] = self.mode.value
        data["confirmation_status"] = self.confirmation_status.value
        data["status"] = self.status.value
        data["created_at"] = self.created_at.isoformat()
        data["finalized_at"] = self.finalized_at.isoformat() if self.finalized_at else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSession:
        verification = data.get("verification") or {}
        capability = data.get("capability") or {}
        target_binding = data.get("target_binding")
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
            confirmation_status=ConfirmationStatus(
                data.get("confirmation_status", ConfirmationStatus.NOT_REQUIRED.value)
            ),
            capability=CapabilityRequest(**capability),
            target_binding=TargetBinding(**target_binding) if target_binding else None,
            approved_target_fingerprint=data.get("approved_target_fingerprint", ""),
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
            evidence_bundle=dict(data.get("evidence_bundle") or {}),
            decision_id=data.get("decision_id", ""),
            asset_id=data.get("asset_id", ""),
            integrity_hmac=data.get("integrity_hmac", ""),
        )


def high_risk_commit(session: AgentSession) -> bool:
    return session.risk in {OperationalRisk.R3, OperationalRisk.R4} and session.mode == ExecutionMode.COMMIT


def validate_session_policy(session: AgentSession) -> list[str]:
    """Return policy violations without making an execution decision.

    High-risk work may still be observed, proposed, or staged. Only a commit
    request requires explicit success and verification criteria. R4 commit
    work additionally requires a rollback or containment path. R3/R4 commit
    work also requires an expiring binding to the exact target and operation.
    """
    violations: list[str] = []
    if session.mode == ExecutionMode.COMMIT and not session.success_criteria:
        violations.append("commit mode requires explicit success criteria.")
    if session.mode == ExecutionMode.COMMIT and not session.verification.expected_outcomes:
        violations.append("commit mode requires a verification plan.")
    if session.risk == OperationalRisk.R4 and session.mode == ExecutionMode.COMMIT and not session.rollback_or_containment:
        violations.append("R4 commit sessions require rollback or containment instructions.")
    if high_risk_commit(session):
        binding = session.target_binding
        if not binding or not binding.kind or not binding.target or not binding.operation or not binding.scope:
            violations.append("R3/R4 commit sessions require a target binding with kind, target, operation, and scope.")
        elif binding.is_expired():
            violations.append("R3/R4 commit target binding is missing, invalid, or expired.")
    return violations
