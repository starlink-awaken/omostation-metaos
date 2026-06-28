from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from metaos.agent_cli import _bind_approval, _require_high_risk_confirmation, _validate_bound_launch
from metaos.core.engine import SEngine
from metaos.core.types import DecisionLevel
from metaos.integrations.agent_runtime.contracts import (
    AgentSession,
    ConfirmationStatus,
    ExecutionMode,
    OperationalRisk,
    ProviderKind,
    SessionStatus,
    TargetBinding,
    VerificationPlan,
)
from metaos.integrations.agent_runtime.service import AgentRuntimeService


class _YellowGate:
    def evaluate(self, _task):
        return DecisionLevel.YELLOW, "explicit confirmation required", None


class _GreenGate:
    def evaluate(self, _task):
        return DecisionLevel.GREEN, "no additional dynamic blocker", None


def _runtime(tmp_path: Path, gate=None) -> AgentRuntimeService:
    engine = SEngine(data_dir=str(tmp_path / "data"))
    engine.gate = gate or _YellowGate()
    return AgentRuntimeService(engine)


def _commit_session(binding: TargetBinding | None) -> AgentSession:
    return AgentSession(
        provider=ProviderKind.CODEX,
        description="Create a calendar event for one recipient",
        risk=OperationalRisk.R3,
        mode=ExecutionMode.COMMIT,
        target_binding=binding,
        success_criteria=["Calendar API returns an event id"],
        verification=VerificationPlan(expected_outcomes=["event id is recorded"]),
    )


def _future_binding() -> TargetBinding:
    return TargetBinding(
        kind="calendar_event",
        target="calendar:primary",
        operation="create_event",
        scope=["recipient:alice@example.com", "duration:30m"],
        expires_at=(datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    )


def test_high_risk_commit_without_target_binding_is_red_blocked(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    prepared, _ = runtime.prepare(_commit_session(None))

    assert prepared.gate_decision == "red"
    assert prepared.status.value == "blocked"
    assert "target binding" in prepared.gate_reason


def test_expired_target_binding_is_red_blocked(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    binding = TargetBinding(
        kind="calendar_event",
        target="calendar:primary",
        operation="create_event",
        scope=["recipient:alice@example.com"],
        expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    )

    prepared, _ = runtime.prepare(_commit_session(binding))

    assert prepared.gate_decision == "red"
    assert "expired" in prepared.gate_reason


def test_green_high_risk_gate_is_elevated_to_pending_human_confirmation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, _GreenGate())
    prepared, _ = runtime.prepare(_commit_session(_future_binding()))

    assert prepared.status == SessionStatus.PREPARED
    elevated = _require_high_risk_confirmation(runtime, prepared, "owner")

    assert elevated.status == SessionStatus.BLOCKED
    assert elevated.gate_decision == "yellow"
    assert elevated.confirmation_status == ConfirmationStatus.PENDING


def test_approval_binds_target_fingerprint_and_rejects_later_target_change(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    binding = _future_binding()
    pending, _ = runtime.prepare(_commit_session(binding))
    approved = runtime.approve(pending, comment="approved only for Alice")
    approved = _bind_approval(runtime, approved, "owner")

    _validate_bound_launch(approved)
    assert approved.approved_target_fingerprint == binding.fingerprint()

    changed = replace(
        approved,
        target_binding=replace(binding, scope=["recipient:bob@example.com", "duration:30m"]),
    )
    with pytest.raises(ValueError, match="differs from the approved target"):
        _validate_bound_launch(changed)
