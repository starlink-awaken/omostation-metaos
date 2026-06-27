from __future__ import annotations

import json
from pathlib import Path

from metaos.core.engine import SEngine
from metaos.core.types import DecisionLevel
from metaos.integrations.agent_runtime.contracts import (
    AgentSession,
    ExecutionMode,
    OperationalRisk,
    ProviderKind,
    SessionStatus,
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


def test_r2_stage_green_session_is_governed_and_finalized(tmp_path: Path) -> None:
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

    assert prepared.status == SessionStatus.RUNNING
    assert prepared.gate_decision == "green"
    assert prepared.asset_id
    assert prepared.decision_id
    assert context.environment["METAOS_GATE_DECISION"] == "green"

    finalized = runtime.finalize(prepared, summary="Patch staged", evidence=["git diff --check"], verification_passed=True)
    assert finalized.status == SessionStatus.FINALIZED
    assert finalized.evidence == ["git diff --check"]


def test_yellow_commit_session_is_blocked_before_provider_launch(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.YELLOW)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        h_id="owner",
        provider=ProviderKind.CLAUDE,
        description="Send a customer email",
        risk=OperationalRisk.R3,
        mode=ExecutionMode.COMMIT,
        success_criteria=["Message accepted by SMTP provider"],
        verification=VerificationPlan(expected_outcomes=["provider receipt"]),
    )

    prepared, context = runtime.prepare(session)

    assert prepared.status == SessionStatus.BLOCKED
    assert prepared.gate_decision == "yellow"
    assert context.environment["METAOS_GATE_DECISION"] == "yellow"


def test_red_gate_blocks_r4_and_emits_trace(tmp_path: Path) -> None:
    engine = _engine(tmp_path, DecisionLevel.RED)
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        h_id="owner",
        provider=ProviderKind.CODEX,
        description="Deploy destructive migration",
        risk=OperationalRisk.R4,
        mode=ExecutionMode.COMMIT,
        success_criteria=["Migration health check passes"],
        verification=VerificationPlan(expected_outcomes=["health endpoint is green"]),
        rollback_or_containment=["restore database snapshot"],
    )

    prepared, _ = runtime.prepare(session)

    assert prepared.status == SessionStatus.BLOCKED
    assert prepared.gate_decision == "red"


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
