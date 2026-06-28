"""Stable JSON rendering helpers for the agent runtime CLI."""

from __future__ import annotations

from .contracts import AgentSession
from .provider_context import ProviderLaunchContext


def prepare_payload(session: AgentSession, context: ProviderLaunchContext) -> dict:
    return {
        "schema_version": "1.0",
        "session": session.to_dict(),
        "launch_context": {
            "environment": context.environment,
            "instruction_block": context.instruction_block,
        },
        "capability_policy": context.capability_policy,
    }
