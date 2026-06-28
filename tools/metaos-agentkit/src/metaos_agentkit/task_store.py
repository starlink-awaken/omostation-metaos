"""Task selection, listing, archival, and cleanup for AgentKit projections.

The canonical MetaOS asset remains authoritative. This module only manages
provider-local projections and their disposable runtime/worktree artifacts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SESSION_FILES = (
    "final-session.json",
    "running-session.json",
    "approved-session.json",
    "prepared-session.json",
    "rejected-session.json",
    "agent-session.json",
)
TERMINAL_STATUSES = {"finalized", "failed", "cancelled"}


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    directory: Path
    archived: bool
    status: str
    risk: str
    mode: str
    description: str
    created_at: str
    finalized_at: str | None
    session_file: Path

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "task_id": self.task_id,
            "directory": str(self.directory),
            "archived": self.archived,
            "status": self.status,
            "risk": self.risk,
            "mode": self.mode,
            "description": self.description,
            "created_at": self.created_at,
            "finalized_at": self.finalized_at,
            "session_file": str(self.session_file),
        }


def active_task_root(project: Path) -> Path:
    return project.resolve() / ".metaos" / "agentkit" / "tasks"


def archived_task_root(project: Path) -> Path:
    return project.resolve() / ".metaos" / "agentkit" / "archive"


def latest_session_file(task_dir: Path) -> Path | None:
    candidates = [task_dir / name for name in SESSION_FILES if (task_dir / name).is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _load_payload(session_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(session_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid AgentKit session projection: {session_file}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"AgentKit session projection is not an object: {session_file}")
    return payload


def read_record(task_dir: Path, *, archived: bool) -> TaskRecord | None:
    session_file = latest_session_file(task_dir)
    if not session_file:
        return None
    payload = _load_payload(session_file)
    task_id = str(payload.get("task_id") or task_dir.name)
    return TaskRecord(
        task_id=task_id,
        directory=task_dir,
        archived=archived,
        status=str(payload.get("status", "unknown")),
        risk=str(payload.get("risk", "")),
        mode=str(payload.get("mode", "")),
        description=str(payload.get("description", "")),
        created_at=str(payload.get("created_at", "")),
        finalized_at=str(payload.get("finalized_at")) if payload.get("finalized_at") else None,
        session_file=session_file,
    )


def list_task_records(project: Path, *, include_archived: bool = False) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    roots = [(active_task_root(project), False)]
    if include_archived:
        roots.append((archived_task_root(project), True))
    for root, archived in roots:
        if not root.exists():
            continue
        for task_dir in root.iterdir():
            if not task_dir.is_dir():
                continue
            record = read_record(task_dir, archived=archived)
            if record:
                records.append(record)
    return sorted(records, key=lambda record: record.created_at or record.directory.name, reverse=True)


def resolve_task_record(
    project: Path,
    *,
    task_id: str | None = None,
    include_archived: bool = False,
    require_explicit_for_high_risk_commit: bool = True,
) -> TaskRecord:
    records = list_task_records(project, include_archived=include_archived)
    if task_id:
        matches = [record for record in records if record.task_id == task_id or record.directory.name == task_id]
        if not matches:
            raise ValueError(f"Task not found: {task_id}")
        if len(matches) > 1:
            raise ValueError(f"Task identifier is ambiguous: {task_id}")
        return matches[0]

    active = [record for record in records if not record.archived and record.status not in TERMINAL_STATUSES]
    if not active:
        raise ValueError("No active AgentKit task found. Create one with `task new`.")
    if len(active) != 1:
        ids = ", ".join(record.task_id for record in active[:5])
        raise ValueError(f"Multiple active tasks exist. Use --task explicitly: {ids}")
    record = active[0]
    if require_explicit_for_high_risk_commit and record.risk in {"R3", "R4"} and record.mode == "commit":
        raise ValueError("R3/R4 commit sessions require an explicit --task identifier.")
    return record


def archive_task(
    *,
    project: Path,
    metaos_home: Path,
    task_id: str,
    apply: bool,
) -> dict[str, Any]:
    record = resolve_task_record(project, task_id=task_id, require_explicit_for_high_risk_commit=False)
    if record.archived:
        raise ValueError(f"Task is already archived: {record.task_id}")
    if record.status not in TERMINAL_STATUSES:
        raise ValueError(f"Only terminal tasks can be archived; {record.task_id} is {record.status}.")

    target = archived_task_root(project) / record.directory.name
    worktree = _worktree_from_launch_audit(record.directory)
    result: dict[str, Any] = {
        "task_id": record.task_id,
        "source": str(record.directory),
        "archive": str(target),
        "worktree": str(worktree) if worktree else None,
        "applied": apply,
    }
    if not apply:
        return result
    if target.exists():
        raise ValueError(f"Archive destination already exists: {target}")
    _remove_managed_worktree(worktree, metaos_home)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(record.directory), str(target))
    return result


def cleanup_terminal_tasks(
    *,
    project: Path,
    metaos_home: Path,
    older_than_days: int,
    apply: bool,
) -> list[dict[str, Any]]:
    if older_than_days < 0:
        raise ValueError("older-than days must be non-negative")
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    candidates: list[TaskRecord] = []
    for record in list_task_records(project):
        if record.status not in TERMINAL_STATUSES:
            continue
        timestamp = _record_timestamp(record)
        if timestamp and timestamp <= cutoff:
            candidates.append(record)
    return [
        archive_task(project=project, metaos_home=metaos_home, task_id=record.task_id, apply=apply)
        for record in candidates
    ]


def _record_timestamp(record: TaskRecord) -> datetime | None:
    value = record.finalized_at or record.created_at
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _worktree_from_launch_audit(task_dir: Path) -> Path | None:
    path = task_dir / "audit" / "launch-plan.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("worktree_path")
    except (OSError, json.JSONDecodeError):
        return None
    return Path(value).expanduser().resolve(strict=False) if value else None


def _remove_managed_worktree(worktree: Path | None, metaos_home: Path) -> None:
    if not worktree or not worktree.exists():
        return
    managed_root = (metaos_home / "agentkit" / "worktrees").resolve()
    candidate = worktree.resolve()
    try:
        inside = os.path.commonpath([str(candidate), str(managed_root)]) == str(managed_root)
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("Refusing to remove a worktree outside the MetaOS-managed worktree root.")
    result = subprocess.run(
        ["git", "-C", str(candidate), "worktree", "remove", "--force", str(candidate)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and candidate.exists():
        raise ValueError(f"Could not remove managed worktree: {(result.stderr or result.stdout).strip()}")
