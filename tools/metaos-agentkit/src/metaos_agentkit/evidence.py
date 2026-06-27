"""Capture reviewable local evidence for an AgentKit finalization."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MAX_EVIDENCE_BYTES = 1_000_000


def capture_finalization_evidence(task_dir: Path) -> Path:
    """Write a bounded, structured evidence bundle owned by the task audit.

    The bundle records local facts that can be obtained without asserting that
    a Provider action succeeded: launch plan, provider exit record, worktree
    Git state, and SHA-256 digests of included audit files.
    """
    task_dir = task_dir.resolve()
    audit = task_dir / "audit"
    launch = audit / "launch-plan.json"
    provider_exit = audit / "provider-exit.json"
    launch_payload = _read_json(launch)
    worktree = _worktree_from_launch(launch_payload)
    bundle: dict[str, Any] = {
        "schema_version": "1.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "task_directory": str(task_dir),
        "audit_files": {
            "launch_plan": _file_descriptor(launch),
            "provider_exit": _file_descriptor(provider_exit),
        },
        "worktree": _git_evidence(worktree) if worktree else {"available": False},
    }
    target = audit / "finalization-evidence.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
    if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        raise ValueError("Generated finalization evidence exceeds the bounded size limit.")
    target.write_text(encoded, encoding="utf-8")
    return target


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _file_descriptor(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"available": False}
    raw = path.read_bytes()
    return {
        "available": True,
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _worktree_from_launch(payload: dict[str, Any] | None) -> Path | None:
    if not payload:
        return None
    value = payload.get("worktree_path")
    return Path(value).expanduser().resolve(strict=False) if value else None


def _git_evidence(worktree: Path) -> dict[str, Any]:
    if not worktree.exists():
        return {"available": False, "path": str(worktree), "reason": "worktree path does not exist"}
    return {
        "available": True,
        "path": str(worktree),
        "head": _git(worktree, ["rev-parse", "HEAD"]),
        "status_porcelain": _git(worktree, ["status", "--porcelain=v1"]),
        "diff_stat": _git(worktree, ["diff", "--stat"]),
        "diff_check": _git(worktree, ["diff", "--check"]),
    }


def _git(worktree: Path, arguments: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "-C", str(worktree), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-20_000:],
        "stderr": result.stderr[-4_000:],
    }
