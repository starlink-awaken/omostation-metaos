"""A2A Task Manager — task lifecycle management for Agent-to-Agent protocol.

A2A Task states:
    submitted → working → completed
                        → failed
                        → canceled
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agora.mcp.mcp_bootstrap import get_data_dir  # type: ignore[import-not-found]


@dataclass
class A2ATask:
    """An A2A-compatible task representing a tool invocation."""

    id: str
    status: str  # submitted | working | completed | failed | canceled
    service_name: str
    tool_name: str
    arguments: dict = field(default_factory=dict)
    session_id: str = ""
    caller_identity: dict = field(default_factory=dict)
    result: dict | None = None
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "service_name": self.service_name,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.session_id:
            d["session_id"] = self.session_id
        if self.caller_identity:
            d["caller_identity"] = self.caller_identity
        if self.result is not None:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        if self.completed_at:
            d["completed_at"] = self.completed_at
        return d


class TaskManager:
    """Manage A2A task lifecycle: create, execute, query, cancel.

    Each task wraps a ``router.route()`` call with task state tracking.
    Tasks are persisted to a JSON file for durability.
    """

    _MAX_TASKS = 1000

    def __init__(self, router, storage_path: str | None = None):
        self._router = router
        self._tasks: dict[str, A2ATask] = {}
        self._storage_path = storage_path or str(get_data_dir() / "agora-tasks.json")
        self._load()

    def _storage_path_obj(self) -> Path:
        return Path(self._storage_path)

    def _load(self):
        """Load tasks from JSON file."""
        path = self._storage_path_obj()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    t = A2ATask(
                        id=item.get("id", ""),
                        status=item.get("status", "submitted"),
                        service_name=item.get("service_name", ""),
                        tool_name=item.get("tool_name", ""),
                        arguments=item.get("arguments", {}),
                        session_id=item.get("session_id", ""),
                        caller_identity=item.get("caller_identity", {}),
                        result=item.get("result"),
                        error=item.get("error", ""),
                        created_at=item.get("created_at", ""),
                        updated_at=item.get("updated_at", ""),
                        completed_at=item.get("completed_at", ""),
                    )
                    self._tasks[t.id] = t
        except (json.JSONDecodeError, OSError):
            pass

    def _save(self):
        """Save tasks to JSON file."""
        data = [t.to_dict() for t in self._tasks.values()]
        path = self._storage_path_obj()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _audit(self, task: A2ATask, event: str) -> None:
        """B-2 P0: 写 A2A 任务审计轨到 append-only JSONL.

        主存储仍是 JSON (可查询), AppendOnlyLog 增 audit trail (跨仓可聚合).
        """
        try:
            from metaos.audit import audit_log
            log = audit_log(self._storage_path_obj().parent / "audit", "a2a-task")
            log.append({
                "ts": self._ts(),
                "task_id": task.id,
                "service": task.service_name,
                "tool": task.tool_name,
                "status": task.status,
                "event": event,
            })
        except Exception:  # noqa: BLE001  # defensive fallback
            # 审计失败不影响主流程
            pass

    def _ts(self) -> str:
        """Current UTC ISO8601 timestamp."""
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def create_task(
        self,
        service_name: str,
        tool_name: str,
        arguments: dict | None = None,
        session_id: str = "",
        caller_identity: dict | None = None,
    ) -> A2ATask:
        """Create a new task in 'submitted' state.

        Args:
            service_name: Target service name (e.g. 'minerva')
            tool_name: Tool name (e.g. 'minerva.research_now')
            arguments: Tool arguments dict
            session_id: Optional session identifier
            caller_identity: Optional structured caller identity

        Returns:
            The newly created A2ATask (status='submitted')
        """
        task = A2ATask(
            id="task_" + secrets.token_hex(8),
            status="submitted",
            service_name=service_name,
            tool_name=tool_name,
            arguments=arguments or {},
            session_id=session_id,
            caller_identity=caller_identity or {},
            created_at=self._ts(),
            updated_at=self._ts(),
        )
        self._tasks[task.id] = task
        self._save()
        self._audit(task, "create")
        return task

    def update_task(
        self,
        task_id: str,
        status: str,
        result: dict | None = None,
        error: str = "",
    ) -> A2ATask | None:
        """Update a task's status and optionally set result or error.

        Returns the updated task, or None if not found.
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        task.status = status
        task.updated_at = self._ts()
        if status in ("completed", "failed", "canceled"):
            task.completed_at = self._ts()
        if result is not None:
            task.result = result
        if error:
            task.error = error
        self._save()
        self._audit(task, f"update:{status}")
        return task

    def get_task(self, task_id: str) -> A2ATask | None:
        """Get a task by its ID. Returns None if not found."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        service: str = "",
        status: str = "",
        since: str = "",
        limit: int = 50,
    ) -> list[A2ATask]:
        """Query tasks with optional filters.

        Args:
            service: Filter by service name
            status: Filter by task status
            since: ISO timestamp lower bound
            limit: Max results (default 50)
        """
        result = list(self._tasks.values())
        if service:
            result = [t for t in result if t.service_name == service]
        if status:
            result = [t for t in result if t.status == status]
        if since:
            result = [t for t in result if t.created_at > since]
        result.sort(key=lambda t: t.created_at, reverse=True)
        return result[:limit]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Only tasks in 'submitted' or 'working' can be canceled.

        Returns True if the task was canceled, False if not found or not cancellable.
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status not in ("submitted", "working"):
            return False
        self.update_task(task_id, "canceled", error="Canceled by user")
        return True

    async def execute_task(self, task_id: str) -> A2ATask | None:
        """Execute a task synchronously via the router.

        Transitions: submitted → working → completed/failed

        Args:
            task_id: The task ID to execute

        Returns:
            The completed task, or None if not found
        """
        task = self._tasks.get(task_id)
        if not task:
            return None

        # Mark as working
        self.update_task(task_id, "working")

        # Execute via router
        try:
            result = await self._router.route(
                task.tool_name,
                task.arguments,
                caller_id=task.caller_identity or "unknown",
            )
            # result is already a dict from router.route()
            self.update_task(task_id, "completed", result=result.get("data", result))
        except Exception as e:  # noqa: BLE001  # defensive fallback
            self.update_task(task_id, "failed", error=str(e)[:500])

        return self._tasks.get(task_id)
