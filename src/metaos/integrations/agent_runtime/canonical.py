"""Canonical session loading for provider-adapter handoffs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import AgentSession
from .integrity import verify_session_dict


def load_canonical_session(engine: Any, submitted: AgentSession) -> AgentSession:
    """Load authoritative session from DLayer; verify integrity HMAC when enabled."""
    if not submitted.asset_id:
        raise ValueError("A canonical session asset is required for this transition.")
    asset_path = Path(engine.d.assets_dir) / f"{submitted.asset_id}.json"
    if not asset_path.exists():
        raise ValueError(f"Canonical session asset is missing: {submitted.asset_id}")
    try:
        stored_asset = json.loads(asset_path.read_text(encoding="utf-8"))
        content = json.loads(stored_asset["content"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Canonical session asset cannot be read.") from exc

    ok, reason = verify_session_dict(content)
    if not ok:
        raise ValueError(f"Canonical session integrity check failed: {reason}")

    try:
        canonical = AgentSession.from_dict(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("Canonical session asset cannot be read.") from exc
    if canonical.session_id != submitted.session_id:
        raise ValueError("Submitted session does not match the canonical session asset.")
    if canonical.asset_id != submitted.asset_id:
        raise ValueError("Submitted asset reference does not match canonical session state.")
    return canonical
