"""Task projection creation with explicit high-risk target binding fields."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from . import service


def create_task(
    *,
    project: Path,
    description: str,
    risk: str,
    mode: str,
    capability_profile: str | None = None,
    allowed_mcp_servers: Iterable[str] = (),
    target_kind: str = "",
    target: str = "",
    operation: str = "",
    scope: Iterable[str] = (),
    expires_in_minutes: int | None = None,
    success_criteria: Iterable[str] = (),
    verification_commands: Iterable[str] = (),
    verification_expected_outcomes: Iterable[str] = (),
    rollback_or_containment: Iterable[str] = (),
) -> Path:
    """Create a local projection with enough data for a governed R3/R4 commit.

    The root runtime remains responsible for canonical validation at prepare.
    This helper only makes the required intent explicit at the CLI boundary.
    """
    high_risk_commit = risk in {"R3", "R4"} and mode == "commit"
    binding_values = [target_kind, target, operation]
    has_partial_binding = any(binding_values) or bool(list(scope)) or expires_in_minutes is not None
    if has_partial_binding and (not all(binding_values) or not list(scope) or expires_in_minutes is None):
        raise ValueError("Target binding requires --target-kind, --target, --operation, at least one --scope, and --expires-in-minutes.")
    if high_risk_commit and not has_partial_binding:
        raise ValueError("R3/R4 commit tasks require an explicit target binding and expiry.")
    if expires_in_minutes is not None and expires_in_minutes <= 0:
        raise ValueError("--expires-in-minutes must be positive.")

    path = service.create_task(
        project=project,
        description=description,
        risk=risk,
        mode=mode,
        capability_profile=capability_profile,
        allowed_mcp_servers=allowed_mcp_servers,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    normalized_scope = list(dict.fromkeys(item.strip() for item in scope if item.strip()))
    if has_partial_binding:
        payload["target_binding"] = {
            "kind": target_kind.strip(),
            "target": target.strip(),
            "operation": operation.strip(),
            "scope": normalized_scope,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=expires_in_minutes or 0)).isoformat(),
            "metadata": {},
        }
    payload["success_criteria"] = list(dict.fromkeys(item.strip() for item in success_criteria if item.strip()))
    payload["verification"] = {
        "commands": list(dict.fromkeys(item.strip() for item in verification_commands if item.strip())),
        "expected_outcomes": list(dict.fromkeys(item.strip() for item in verification_expected_outcomes if item.strip())),
        "notes": [],
    }
    payload["rollback_or_containment"] = list(
        dict.fromkeys(item.strip() for item in rollback_or_containment if item.strip())
    ) or payload.get("rollback_or_containment", [])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
