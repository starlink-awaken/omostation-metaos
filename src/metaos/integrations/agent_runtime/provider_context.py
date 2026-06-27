"""Provider-facing projections of canonical MetaOS sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .contracts import AgentSession


@dataclass(frozen=True)
class ProviderLaunchContext:
    environment: dict[str, str]
    instruction_block: str


def build_provider_context(session: AgentSession, session_asset_path: str = "") -> ProviderLaunchContext:
    """Build non-secret context for a provider adapter.

    This function deliberately does not grant capabilities. It only projects
    the already-governed session state into provider-readable environment and
    instruction text.
    """
    env = {
        "METAOS_AGENT_SESSION_ID": session.session_id,
        "METAOS_TASK_ID": session.task_id,
        "METAOS_MODE": session.mode.value,
        "METAOS_RISK": session.risk.value,
        "METAOS_GATE_DECISION": session.gate_decision,
        "METAOS_CAPABILITY_PROFILE": session.capability.profile,
    }
    if session_asset_path:
        env["METAOS_SESSION_ASSET"] = session_asset_path
    block = "\n".join(
        [
            "# MetaOS Agent Session",
            f"- session: {session.session_id}",
            f"- risk: {session.risk.value}",
            f"- mode: {session.mode.value}",
            f"- gate: {session.gate_decision}",
            f"- capability profile: {session.capability.profile}",
            "- Treat this session contract as a boundary, not as permission escalation.",
            "- Do not execute external writes, commits, deployments, or account actions when gate is yellow/red.",
            "- Report produced artifacts and verification outcomes for MetaOS finalization.",
        ]
    )
    return ProviderLaunchContext(environment=env, instruction_block=block)


def write_session_projection(session: AgentSession, directory: Path) -> Path:
    """Write a provider-readable projection; canonical state remains in DLayer."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "agent-session.json"
    target.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
