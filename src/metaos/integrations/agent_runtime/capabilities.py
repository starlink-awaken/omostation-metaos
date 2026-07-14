"""Canonical capability profiles for provider-session enforcement.

Profiles are intentionally conservative. They define the maximum authority an
adapter may project into a provider; they do not grant authority on their own.
The existing MetaOS gate can still reduce a session to blocked.

Phase D: YAML overlay via METAOS_CAPABILITY_PROFILES or ~/.metaos/capability-profiles.yaml
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .contracts import AgentSession, ExecutionMode, OperationalRisk
from .mcp_policy import parse_mcp_requests
from .mcp_policy import requested_mcp_servers as _requested_mcp_servers

logger = logging.getLogger("metaos.agent_runtime.capabilities")


@dataclass(frozen=True)
class CapabilityProfile:
    name: str
    allowed_risks: tuple[OperationalRisk, ...]
    allowed_modes: tuple[ExecutionMode, ...]
    codex_sandbox: str
    codex_approval: str
    network: bool
    isolate_git_worktree: bool
    allow_explicit_mcp: bool
    require_human_confirmation_for_launch: bool
    description: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_risks"] = [risk.value for risk in self.allowed_risks]
        data["allowed_modes"] = [mode.value for mode in self.allowed_modes]
        return data


PROFILES: dict[str, CapabilityProfile] = {
    "core": CapabilityProfile(
        name="core",
        allowed_risks=(OperationalRisk.R0, OperationalRisk.R1),
        allowed_modes=(ExecutionMode.OBSERVE, ExecutionMode.PROPOSE),
        codex_sandbox="read-only",
        codex_approval="on-request",
        network=False,
        isolate_git_worktree=False,
        allow_explicit_mcp=False,
        require_human_confirmation_for_launch=False,
        description="Text and low-impact read-only work; no MCP servers.",
    ),
    "repo-read": CapabilityProfile(
        name="repo-read",
        allowed_risks=(OperationalRisk.R1,),
        allowed_modes=(ExecutionMode.OBSERVE, ExecutionMode.PROPOSE),
        codex_sandbox="read-only",
        codex_approval="on-request",
        network=False,
        isolate_git_worktree=False,
        allow_explicit_mcp=False,
        require_human_confirmation_for_launch=False,
        description="Read-only repository inspection; no MCP servers.",
    ),
    "research-read": CapabilityProfile(
        name="research-read",
        allowed_risks=(OperationalRisk.R1,),
        allowed_modes=(ExecutionMode.OBSERVE, ExecutionMode.PROPOSE),
        codex_sandbox="read-only",
        codex_approval="on-request",
        network=False,
        isolate_git_worktree=False,
        allow_explicit_mcp=True,
        require_human_confirmation_for_launch=False,
        description="Read-only research; explicitly named read-only MCP servers may be projected.",
    ),
    "repo-stage": CapabilityProfile(
        name="repo-stage",
        allowed_risks=(OperationalRisk.R2,),
        allowed_modes=(ExecutionMode.STAGE,),
        codex_sandbox="workspace-write",
        codex_approval="on-request",
        network=False,
        isolate_git_worktree=True,
        allow_explicit_mcp=False,
        require_human_confirmation_for_launch=False,
        description="Focused code or configuration changes in an isolated Git worktree; no MCP servers.",
    ),
    "high-risk-stage": CapabilityProfile(
        name="high-risk-stage",
        allowed_risks=(OperationalRisk.R3, OperationalRisk.R4),
        allowed_modes=(ExecutionMode.STAGE,),
        codex_sandbox="workspace-write",
        codex_approval="on-request",
        network=False,
        isolate_git_worktree=True,
        allow_explicit_mcp=False,
        require_human_confirmation_for_launch=False,
        description="High-risk planning, rehearsal, or reviewable patch generation in an isolated worktree; no external effects or MCP servers.",
    ),
    "external-commit": CapabilityProfile(
        name="external-commit",
        allowed_risks=(OperationalRisk.R3, OperationalRisk.R4),
        allowed_modes=(ExecutionMode.COMMIT,),
        codex_sandbox="workspace-write",
        codex_approval="on-request",
        network=False,
        isolate_git_worktree=False,
        allow_explicit_mcp=True,
        require_human_confirmation_for_launch=True,
        description="High-impact commit work; only explicitly named MCP servers may be projected after gate approval.",
    ),
}


def default_profile_name(session: AgentSession) -> str:
    if session.risk == OperationalRisk.R2 and session.mode == ExecutionMode.STAGE:
        return "repo-stage"
    if session.risk in {OperationalRisk.R3, OperationalRisk.R4} and session.mode == ExecutionMode.STAGE:
        return "high-risk-stage"
    if session.risk in {OperationalRisk.R3, OperationalRisk.R4} and session.mode == ExecutionMode.COMMIT:
        return "external-commit"
    if session.risk == OperationalRisk.R1:
        return "repo-read"
    return "core"


def _profile_policy_path() -> Path | None:
    env = os.environ.get("METAOS_CAPABILITY_PROFILES", "").strip()
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() else None
    home = Path.home() / ".metaos" / "capability-profiles.yaml"
    if home.is_file():
        return home
    pkg = Path(__file__).resolve().parent.parent.parent / "config" / "capability-profiles.yaml"
    return pkg if pkg.is_file() else None


def _parse_profile_entry(name: str, raw: dict[str, Any]) -> CapabilityProfile:
    required = (
        "allowed_risks",
        "allowed_modes",
        "codex_sandbox",
        "codex_approval",
        "network",
        "isolate_git_worktree",
        "allow_explicit_mcp",
        "require_human_confirmation_for_launch",
    )
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"profile {name} missing fields: {missing}")
    return CapabilityProfile(
        name=name,
        allowed_risks=tuple(OperationalRisk(x) for x in raw["allowed_risks"]),
        allowed_modes=tuple(ExecutionMode(x) for x in raw["allowed_modes"]),
        codex_sandbox=str(raw["codex_sandbox"]),
        codex_approval=str(raw["codex_approval"]),
        network=bool(raw["network"]),
        isolate_git_worktree=bool(raw["isolate_git_worktree"]),
        allow_explicit_mcp=bool(raw["allow_explicit_mcp"]),
        require_human_confirmation_for_launch=bool(raw["require_human_confirmation_for_launch"]),
        description=str(raw.get("description") or f"User profile {name}"),
    )


_profiles_overlay_loaded = False


def load_profile_overlays(force: bool = False) -> dict[str, CapabilityProfile]:
    """Merge YAML overlays into PROFILES by name."""
    global _profiles_overlay_loaded
    if _profiles_overlay_loaded and not force:
        return PROFILES
    path = _profile_policy_path()
    _profiles_overlay_loaded = True
    if not path:
        return PROFILES
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("capability profile file unreadable %s: %s", path, e)
        return PROFILES
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict):
        logger.warning("capability profile file missing 'profiles' map: %s", path)
        return PROFILES
    for name, raw in profiles.items():
        if not isinstance(raw, dict):
            continue
        try:
            PROFILES[str(name)] = _parse_profile_entry(str(name), raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("invalid profile %s: %s", name, e)
    return PROFILES


def resolve_profile(session: AgentSession) -> CapabilityProfile:
    load_profile_overlays()
    name = session.capability.profile or default_profile_name(session)
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown capability profile: {name}") from exc


def validate_capability_profile(session: AgentSession) -> list[str]:
    """Return contract violations before a provider adapter receives authority."""
    try:
        profile = resolve_profile(session)
    except ValueError as exc:
        return [str(exc)]

    violations: list[str] = []
    if session.risk not in profile.allowed_risks:
        violations.append(f"Profile {profile.name} does not allow risk {session.risk.value}.")
    if session.mode not in profile.allowed_modes:
        violations.append(f"Profile {profile.name} does not allow mode {session.mode.value}.")
    requested_mcp = [item for item in session.capability.requested if item.startswith("mcp:")]
    if requested_mcp and not profile.allow_explicit_mcp:
        violations.append(f"Profile {profile.name} does not permit MCP server requests.")
    try:
        parse_mcp_requests(requested_mcp)
    except ValueError as exc:
        violations.append(str(exc))
    return violations


def requested_mcp_servers(session: AgentSession) -> tuple[str, ...]:
    """Return uniquely requested MCP server names after canonical validation."""
    return _requested_mcp_servers(session.capability.requested)
