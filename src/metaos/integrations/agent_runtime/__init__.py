"""Provider-neutral agent runtime integration for MetaOS.

This package is the convergence boundary between MetaOS governance and
provider-specific adapters such as Codex or Claude Code.
"""

from .capabilities import CapabilityProfile, PROFILES, resolve_profile
from .contracts import (
    AgentSession,
    ConfirmationStatus,
    ExecutionMode,
    OperationalRisk,
    ProviderKind,
    SessionStatus,
)
from .service import AgentRuntimeService

__all__ = [
    "AgentRuntimeService",
    "AgentSession",
    "CapabilityProfile",
    "ConfirmationStatus",
    "ExecutionMode",
    "OperationalRisk",
    "PROFILES",
    "ProviderKind",
    "SessionStatus",
    "resolve_profile",
]
