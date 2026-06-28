from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from metaos_agentkit.task_store import (
    archive_task,
    cleanup_terminal_tasks,
    list_task_records,
    resolve_task_record,
)


def _write_task(
    project: Path,
    task_id: str,
    *,
    status: str = "prepared",
    risk: str = "R2",
    mode: str = "stage",
    created_at: datetime | None = None,
    finalized_at: datetime | None = None,
) -> Path:
    directory = project / ".metaos" / "agentkit" / "tasks" / task_id
    directory.mkdir(parents=True)
    payload = {
        "task_id": task_id,
        "session_id": f"agent-{task_id}",
        "description": task_id,
        "risk": risk,
        "mode": mode,
        "status": status,
        "created_at": (created_at or datetime.now(UTC)).isoformat(),
        "finalized_at": finalized_at.isoformat() if finalized_at else None,
    }
    name = "final-session.json" if status in {"finalized", "failed", "cancelled"} else "agent-session.json"
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_multiple_active_tasks_require_explicit_selection(tmp_path: Path) -> None:
    _write_task(tmp_path, "task-one")
    _write_task(tmp_path, "task-two")

    with pytest.raises(ValueError, match="Multiple active tasks"):
        resolve_task_record(tmp_path)

    selected = resolve_task_record(tmp_path, task_id="task-two")
    assert selected.task_id == "task-two"


def test_high_risk_commit_requires_explicit_task_even_when_only_one_exists(tmp_path: Path) -> None:
    _write_task(tmp_path, "task-commit", risk="R4", mode="commit")

    with pytest.raises(ValueError, match="require an explicit --task"):
        resolve_task_record(tmp_path)

    selected = resolve_task_record(tmp_path, task_id="task-commit")
    assert selected.risk == "R4"
    assert selected.mode == "commit"


def test_archive_only_moves_terminal_task_and_keeps_projection(tmp_path: Path) -> None:
    _write_task(tmp_path, "task-done", status="finalized", finalized_at=datetime.now(UTC))

    preview = archive_task(project=tmp_path, metaos_home=tmp_path / "home" / ".metaos", task_id="task-done", apply=False)
    assert preview["applied"] is False
    assert (tmp_path / ".metaos" / "agentkit" / "tasks" / "task-done").exists()

    result = archive_task(project=tmp_path, metaos_home=tmp_path / "home" / ".metaos", task_id="task-done", apply=True)
    assert result["applied"] is True
    assert not (tmp_path / ".metaos" / "agentkit" / "tasks" / "task-done").exists()
    assert (tmp_path / ".metaos" / "agentkit" / "archive" / "task-done" / "final-session.json").exists()


def test_cleanup_archives_only_old_terminal_tasks(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    _write_task(tmp_path, "task-old", status="finalized", finalized_at=now - timedelta(days=30))
    _write_task(tmp_path, "task-new", status="finalized", finalized_at=now - timedelta(days=1))
    _write_task(tmp_path, "task-active", status="running", created_at=now - timedelta(days=60))

    preview = cleanup_terminal_tasks(project=tmp_path, metaos_home=tmp_path / "home" / ".metaos", older_than_days=14, apply=False)
    assert [item["task_id"] for item in preview] == ["task-old"]

    applied = cleanup_terminal_tasks(project=tmp_path, metaos_home=tmp_path / "home" / ".metaos", older_than_days=14, apply=True)
    assert [item["task_id"] for item in applied] == ["task-old"]
    records = {record.task_id: record for record in list_task_records(tmp_path, include_archived=True)}
    assert records["task-old"].archived is True
    assert records["task-new"].archived is False
    assert records["task-active"].archived is False
