from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

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


class _Gate:
    def __init__(self, level: DecisionLevel, reason: str = "test gate") -> None:
        self.level = level
        self.reason = reason

    def evaluate(self, _task):
        return self.level, self.reason, None


def _engine(tmp_path: Path, level: DecisionLevel) -> SEngine:
    engine = SEngine(data_dir=str(tmp_path / "data"))
    engine.gate = _Gate(level)
    return engine


def _binding(*, kind: str, target: str, operation: str, scope: list[str]) -> TargetBinding:
    return TargetBinding(
        kind=kind,
        target=target,
        operation=operation,
        scope=scope,
        expires_at=(datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    )


def test_r2_stage_green_session_is_prepared_then_finalized(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.GREEN)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        h_id="owner",
        provider=ProviderKind.CODEX,
        description="Fix a focused type error",
        risk=OperationalRisk.R2,
        mode=ExecutionMode.STAGE,
    )

    prepared, context = runtime.prepare(session)

    assert prepared.status == SessionStatus.PREPARED
    assert prepared.gate_decision == "green"
    assert prepared.asset_id
    assert prepared.decision_id
    assert context.environment["METAOS_GATE_DECISION"] == "green"

    running = runtime.mark_running(prepared)
    assert running.status == SessionStatus.RUNNING
    finalized = runtime.finalize(running, summary="Patch staged", evidence=["git diff --check"], verification_passed=True)
    assert finalized.status == SessionStatus.FINALIZED
    assert finalized.evidence == ["git diff --check"]
    trace = engine.d.get_asset_trace(finalized.asset_id)
    assert any(entry["event"] == "agent_session_finalized" for entry in trace["logs"])


def test_yellow_commit_session_requires_human_approval_before_launch(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.YELLOW)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        h_id="owner",
        provider=ProviderKind.CLAUDE,
        description="Send a customer email",
        risk=OperationalRisk.R3,
        mode=ExecutionMode.COMMIT,
        target_binding=_binding(
            kind="email",
            target="mailto:alice@example.com",
            operation="send",
            scope=["subject:status update"],
        ),
        success_criteria=["Message accepted by SMTP provider"],
        verification=VerificationPlan(expected_outcomes=["provider receipt"]),
    )

    blocked, context = runtime.prepare(session)

    assert blocked.status == SessionStatus.BLOCKED
    assert blocked.gate_decision == "yellow"
    assert blocked.confirmation_status == ConfirmationStatus.PENDING
    assert context.environment["METAOS_GATE_DECISION"] == "yellow"

    approved = runtime.approve(blocked, comment="approved for this recipient")
    assert approved.status == SessionStatus.PREPARED
    assert approved.confirmation_status == ConfirmationStatus.APPROVED
    assert runtime.mark_running(approved).status == SessionStatus.RUNNING


def test_red_gate_blocks_r4_and_emits_trace(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.RED)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        h_id="owner",
        provider=ProviderKind.CODEX,
        description="Deploy destructive migration",
        risk=OperationalRisk.R4,
        mode=ExecutionMode.COMMIT,
        target_binding=_binding(
            kind="database_migration",
            target="production:primary",
            operation="apply",
            scope=["migration:20260628_add_index"],
        ),
        success_criteria=["Migration health check passes"],
        verification=VerificationPlan(expected_outcomes=["health endpoint is green"]),
        rollback_or_containment=["restore database snapshot"],
    )

    prepared, _ = runtime.prepare(session)

    assert prepared.status == SessionStatus.BLOCKED
    assert prepared.gate_decision == "red"
    assert prepared.confirmation_status == ConfirmationStatus.NOT_REQUIRED


def test_invalid_commit_policy_blocks_before_gate(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.GREEN)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        provider=ProviderKind.CODEX,
        description="Deploy without verification plan",
        risk=OperationalRisk.R3,
        mode=ExecutionMode.COMMIT,
    )

    prepared, _ = runtime.prepare(session)

    assert prepared.status == SessionStatus.BLOCKED
    assert prepared.gate_decision == "red"
    assert "success criteria" in prepared.gate_reason


def test_r4_can_be_staged_without_premature_commit_requirements(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.GREEN)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        provider=ProviderKind.CODEX,
        description="Plan a destructive migration without executing it",
        risk=OperationalRisk.R4,
        mode=ExecutionMode.STAGE,
    )

    prepared, _ = runtime.prepare(session)

    assert prepared.status == SessionStatus.PREPARED
    assert prepared.gate_decision == "green"
