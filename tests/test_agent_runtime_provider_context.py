from __future__ import annotations

from pathlib import Path

from metaos.integrations.agent_runtime.contracts import (
    AgentSession,
    CapabilityRequest,
    ExecutionMode,
    OperationalRisk,
    ProviderKind,
)
from metaos.integrations.agent_runtime.provider_context import build_provider_context, write_session_projection


def test_provider_context_projects_limits_without_granting_capabilities(tmp_path: Path) -> None:
    session = AgentSession(
        provider=ProviderKind.CODEX,
        description="Stage a patch",
        risk=OperationalRisk.R2,
        mode=ExecutionMode.STAGE,
        capability=CapabilityRequest(profile="repo-stage"),
    )
    context = build_provider_context(session, session_asset_path="asset:session-1")

    assert context.environment["METAOS_MODE"] == "stage"
    assert context.environment["METAOS_SESSION_ASSET"] == "asset:session-1"
    assert context.capability_policy["name"] == "repo-stage"
    assert context.capability_policy["codex_sandbox"] == "workspace-write"
    assert context.capability_policy["allowed_mcp_servers"] == []
    assert "not as permission escalation" in context.instruction_block

    target = write_session_projection(session, tmp_path)
    assert target.name == "agent-session.json"
    assert '"mode": "stage"' in target.read_text(encoding="utf-8")
