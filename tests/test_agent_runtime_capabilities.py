from __future__ import annotations

from pathlib import Path

from metaos.core.engine import SEngine
from metaos.core.types import DecisionLevel
from metaos.integrations.agent_runtime.capabilities import (
    requested_mcp_servers,
    resolve_profile,
    validate_capability_profile,
)
from metaos.integrations.agent_runtime.contracts import (
    AgentSession,
    CapabilityRequest,
    ExecutionMode,
    OperationalRisk,
    ProviderKind,
    SessionStatus,
)
from metaos.integrations.agent_runtime.provider_context import build_provider_context
from metaos.integrations.agent_runtime.service import AgentRuntimeService


class _GreenGate:
    def evaluate(self, _task):
        return DecisionLevel.GREEN, "test gate", None


def _session(
    *,
    risk: OperationalRisk,
    mode: ExecutionMode,
    profile: str,
    requested: list[str] | None = None,
) -> AgentSession:
    return AgentSession(
        provider=ProviderKind.CODEX,
        description="capability test",
        risk=risk,
        mode=mode,
        capability=CapabilityRequest(profile=profile, requested=requested or []),
    )


def test_repo_stage_allows_only_r2_stage() -> None:
    valid = _session(risk=OperationalRisk.R2, mode=ExecutionMode.STAGE, profile="repo-stage")
    invalid = _session(risk=OperationalRisk.R2, mode=ExecutionMode.COMMIT, profile="repo-stage")

    assert validate_capability_profile(valid) == []
    assert "does not allow mode commit" in validate_capability_profile(invalid)[0]


def test_mcp_requests_require_an_explicit_mcp_capable_profile() -> None:
    forbidden = _session(
        risk=OperationalRisk.R2,
        mode=ExecutionMode.STAGE,
        profile="repo-stage",
        requested=["mcp:repo-index"],
    )
    allowed = _session(
        risk=OperationalRisk.R1,
        mode=ExecutionMode.OBSERVE,
        profile="research-read",
        requested=["mcp:web-reader", "mcp:web-reader", "mcp:docs"],
    )

    assert "does not permit MCP" in validate_capability_profile(forbidden)[0]
    assert validate_capability_profile(allowed) == []
    assert requested_mcp_servers(allowed) == ("web-reader", "docs")


def test_provider_context_carries_resolved_policy_without_granting_unrequested_mcp() -> None:
    session = _session(
        risk=OperationalRisk.R1,
        mode=ExecutionMode.OBSERVE,
        profile="research-read",
        requested=["mcp:web-reader"],
    )
    context = build_provider_context(session, session_asset_path="asset:session-test")

    assert context.capability_policy["name"] == "research-read"
    assert context.capability_policy["allowed_mcp_servers"] == ["web-reader"]
    assert context.environment["METAOS_ALLOWED_MCP_JSON"] == '["web-reader"]'
    assert "permission escalation" in context.instruction_block


def test_invalid_profile_is_blocked_before_gate_execution(tmp_path: Path) -> None:
    engine = SEngine(data_dir=str(tmp_path / "data"))
    engine.gate = _GreenGate()
    runtime = AgentRuntimeService(engine)
    session = _session(risk=OperationalRisk.R1, mode=ExecutionMode.OBSERVE, profile="does-not-exist")

    prepared, context = runtime.prepare(session)

    assert prepared.status == SessionStatus.BLOCKED
    assert prepared.gate_decision == "red"
    assert "Unknown capability profile" in prepared.gate_reason
    assert context.capability_policy["name"] == "blocked"
    assert context.capability_policy["allowed_mcp_servers"] == []
