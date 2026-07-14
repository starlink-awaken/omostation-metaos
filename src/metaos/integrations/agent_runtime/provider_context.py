"""Provider-facing projections of canonical MetaOS sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capabilities import requested_mcp_servers, resolve_profile
from .contracts import AgentSession
from .mcp_policy import requested_mcp_tools


@dataclass(frozen=True)
class ProviderLaunchContext:
    environment: dict[str, str]
    instruction_block: str
    capability_policy: dict[str, Any]


def build_provider_context(session: AgentSession, session_asset_path: str = "") -> ProviderLaunchContext:
    """Build a non-secret projection of an already-governed session.

    The returned policy is declarative. Provider adapters must translate it
    into real provider settings, sandbox flags, hooks, and MCP restrictions;
    it never grants authority beyond those enforcement mechanisms.
    """
    profile = resolve_profile(session)
    allowed_mcp = requested_mcp_servers(session)
    allowed_mcp_tools = requested_mcp_tools(session.capability.requested)
    policy = {
        **profile.to_dict(),
        "allowed_mcp_servers": list(allowed_mcp),
        "allowed_mcp_tools": {server: list(tools) for server, tools in allowed_mcp_tools.items()},
        "session_status": session.status.value,
        "gate_decision": session.gate_decision,
        "confirmation_status": session.confirmation_status.value,
    }
    return _context_from_policy(session, policy, profile.name, allowed_mcp, allowed_mcp_tools, session_asset_path)


def build_blocked_provider_context(
    session: AgentSession,
    *,
    session_asset_path: str = "",
    reason: str = "capability policy is invalid",
) -> ProviderLaunchContext:
    """Return a projection that is safe to serialize but cannot authorize launch."""
    policy = {
        "name": "blocked",
        "allowed_risks": [],
        "allowed_modes": [],
        "codex_sandbox": "read-only",
        "codex_approval": "on-request",
        "network": False,
        "isolate_git_worktree": False,
        "allow_explicit_mcp": False,
        "require_human_confirmation_for_launch": True,
        "allowed_mcp_servers": [],
        "allowed_mcp_tools": {},
        "session_status": session.status.value,
        "gate_decision": session.gate_decision,
        "confirmation_status": session.confirmation_status.value,
        "reason": reason,
    }
    return _context_from_policy(session, policy, "blocked", (), {}, session_asset_path)


def _context_from_policy(
    session: AgentSession,
    policy: dict[str, Any],
    profile_name: str,
    allowed_mcp: tuple[str, ...],
    allowed_mcp_tools: dict[str, tuple[str, ...]],
    session_asset_path: str,
) -> ProviderLaunchContext:
    env = {
        "METAOS_AGENT_SESSION_ID": session.session_id,
        "METAOS_TASK_ID": session.task_id,
        "METAOS_MODE": session.mode.value,
        "METAOS_RISK": session.risk.value,
        "METAOS_GATE_DECISION": session.gate_decision,
        "METAOS_CAPABILITY_PROFILE": profile_name,
        "METAOS_ALLOWED_MCP_JSON": json.dumps(list(allowed_mcp)),
        "METAOS_ALLOWED_MCP_TOOLS_JSON": json.dumps(
            {server: list(tools) for server, tools in allowed_mcp_tools.items()}
        ),
        "METAOS_CAPABILITY_POLICY_JSON": json.dumps(policy, sort_keys=True),
    }
    if session_asset_path:
        env["METAOS_SESSION_ASSET"] = session_asset_path
    formatted_tools = ", ".join(f"{server}:{'/'.join(tools)}" for server, tools in allowed_mcp_tools.items())
    block = "\n".join(
        [
            "# MetaOS Agent Session",
            f"- session: {session.session_id}",
            f"- risk: {session.risk.value}",
            f"- mode: {session.mode.value}",
            f"- gate: {session.gate_decision}",
            f"- capability profile: {profile_name}",
            f"- explicitly allowed MCP tools: {formatted_tools or '(none)'}",
            "- Treat this session contract as a boundary, not as permission escalation.",
            "- Do not execute blocked work or unapproved yellow-gate commit work.",
            "- Report produced artifacts and verification outcomes for MetaOS finalization.",
        ]
    )
    return ProviderLaunchContext(environment=env, instruction_block=block, capability_policy=policy)


def write_session_projection(session: AgentSession, directory: Path) -> Path:
    """Write a provider-readable projection; canonical state remains in DLayer."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "agent-session.json"
    target.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
