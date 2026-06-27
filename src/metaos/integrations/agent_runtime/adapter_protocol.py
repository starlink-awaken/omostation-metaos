"""Protocol for provider adapters.

Adapters translate canonical sessions into provider-specific files and launch
mechanisms. They are intentionally not allowed to decide gate outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .contracts import AgentSession
from .provider_context import ProviderLaunchContext


class ProviderAdapter(Protocol):
    provider_name: str

    def project(self, session: AgentSession, target_dir: Path) -> ProviderLaunchContext:
        """Create provider-readable projections for an already-prepared session."""

    def launch_command(self, context: ProviderLaunchContext, extra_args: list[str] | None = None) -> list[str]:
        """Return a command without executing it."""
