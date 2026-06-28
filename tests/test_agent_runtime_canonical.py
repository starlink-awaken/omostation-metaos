from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from metaos.core.engine import SEngine
from metaos.core.types import DecisionLevel
from metaos.integrations.agent_runtime.canonical import load_canonical_session
from metaos.integrations.agent_runtime.contracts import AgentSession, ExecutionMode, OperationalRisk, ProviderKind
from metaos.integrations.agent_runtime.service import AgentRuntimeService


class _GreenGate:
    def evaluate(self, _task):
        return DecisionLevel.GREEN, "test gate", None


def test_canonical_asset_overrides_tampered_projection(tmp_path: Path) -> None:
    engine = SEngine(data_dir=str(tmp_path / "data"))
    engine.gate = _GreenGate()
    runtime = AgentRuntimeService(engine)
    session = AgentSession(
        provider=ProviderKind.CODEX,
        description="Stage a focused patch",
        risk=OperationalRisk.R2,
        mode=ExecutionMode.STAGE,
    )
    prepared, _ = runtime.prepare(session)

    tampered = replace(
        prepared,
        risk=OperationalRisk.R4,
        mode=ExecutionMode.COMMIT,
        gate_decision="green",
        confirmation_status="approved",  # type: ignore[arg-type]
    )
    canonical = load_canonical_session(engine, tampered)

    assert canonical.risk == OperationalRisk.R2
    assert canonical.mode == ExecutionMode.STAGE
    assert canonical.asset_id == prepared.asset_id


def test_canonical_loader_rejects_cross_session_asset_substitution(tmp_path: Path) -> None:
    engine = SEngine(data_dir=str(tmp_path / "data"))
    engine.gate = _GreenGate()
    runtime = AgentRuntimeService(engine)
    first, _ = runtime.prepare(
        AgentSession(provider=ProviderKind.CODEX, description="first", risk=OperationalRisk.R2, mode=ExecutionMode.STAGE)
    )
    second, _ = runtime.prepare(
        AgentSession(provider=ProviderKind.CODEX, description="second", risk=OperationalRisk.R2, mode=ExecutionMode.STAGE)
    )

    substituted = replace(first, asset_id=second.asset_id)
    with pytest.raises(ValueError, match="does not match"):
        load_canonical_session(engine, substituted)
