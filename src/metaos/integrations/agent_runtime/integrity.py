"""Canonical session integrity HMAC (ADR-0181 Phase 4c / Agent Runtime Phase D).

Protects multi-process handoffs: DLayer asset content is signed so a stale or
tampered provider-local projection cannot silently advance lifecycle state.

Env:
  METAOS_SESSION_INTEGRITY_SECRET — HMAC key (empty = signing disabled, verify skips)
  METAOS_SESSION_INTEGRITY_REQUIRED=1 — reject load when signature missing/invalid
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

INTEGRITY_FIELD = "integrity_hmac"


def integrity_secret() -> str:
    return os.environ.get("METAOS_SESSION_INTEGRITY_SECRET", "").strip()


def integrity_required() -> bool:
    return os.environ.get("METAOS_SESSION_INTEGRITY_REQUIRED", "0").strip() == "1"


def canonical_bytes(data: dict[str, Any]) -> bytes:
    """Stable serialization excluding the integrity field itself."""
    body = {k: v for k, v in data.items() if k != INTEGRITY_FIELD}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_session_dict(data: dict[str, Any], secret: str | None = None) -> str:
    key = (secret if secret is not None else integrity_secret()).encode("utf-8")
    if not key:
        return ""
    return hmac.new(key, canonical_bytes(data), hashlib.sha256).hexdigest()


def attach_integrity(data: dict[str, Any], secret: str | None = None) -> dict[str, Any]:
    """Return copy with integrity_hmac set (or cleared if no secret)."""
    out = dict(data)
    out.pop(INTEGRITY_FIELD, None)
    sig = sign_session_dict(out, secret=secret)
    if sig:
        out[INTEGRITY_FIELD] = sig
    return out


def verify_session_dict(data: dict[str, Any], secret: str | None = None) -> tuple[bool, str]:
    """Verify integrity_hmac. Returns (ok, reason)."""
    key = secret if secret is not None else integrity_secret()
    if not key:
        if integrity_required():
            return False, "integrity_secret_missing"
        return True, "integrity_disabled"
    expected = data.get(INTEGRITY_FIELD, "")
    if not expected:
        if integrity_required():
            return False, "integrity_missing"
        return True, "integrity_absent_allowed"
    actual = sign_session_dict(data, secret=key)
    if not hmac.compare_digest(str(expected), actual):
        return False, "integrity_mismatch"
    return True, "ok"
