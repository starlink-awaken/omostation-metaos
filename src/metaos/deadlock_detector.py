"""Deadlock Detector — DFS cycle detection + timeout + READONLY resolution.

Tracks Agent dependency graphs to detect circular waits (deadlocks),
flags long-running waits (>5 min), and suggests READONLY release strategies.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

READONLY_MSG = "READONLY: requires human confirmation — simulation only, no production effect"


class DeadlockDetector:
    """Agent deadlock detection with DFS cycle analysis and READONLY resolution.

    Maintains a resource allocation graph (RAG) where edges represent
    "Agent A is waiting for Agent B".  Detects cycles via DFS, flags
    long waits via timeout checks, and suggests which Agent to terminate.
    """

    TIMEOUT_SEC = 300  # 5 minutes

    def __init__(self):
        # Dependency graph: waiting_agent → {held_by_agent: resource_id}
        self._edges: dict[str, dict[str, str]] = {}
        # Agent metadata
        self._agent_priority: dict[str, int] = {}
        self._checkpoints: dict[str, str] = {}
        # Wait tracking for timeout detection
        self._wait_starts: dict[str, float] = {}
        # Cross-layer alerts
        self._alerts: list[dict[str, Any]] = []

    # ── Agent Registration ──

    def register_agent(self, agent_id: str, priority: int = 2) -> dict:
        """Register an agent with a priority level.

        Priority follows the same convention as kos.task_dispatcher:
        P0=0 (highest) through P3=3 (lowest).
        """
        self._agent_priority[agent_id] = priority
        return {"ok": True, "agent_id": agent_id}

    # ── Dependency Management ──

    def add_dependency(self, waiting_agent: str, held_by: str, resource_id: str = "unknown") -> dict:
        """Record that *waiting_agent* is waiting for *held_by*.

        Both agents must be registered first.
        """
        if waiting_agent not in self._agent_priority:
            return {"error": f"unknown_agent: {waiting_agent}"}
        if held_by not in self._agent_priority:
            return {"error": f"unknown_agent: {held_by}"}

        if waiting_agent not in self._edges:
            self._edges[waiting_agent] = {}
        self._edges[waiting_agent][held_by] = resource_id

        # Track wait start time for timeout detection
        if waiting_agent not in self._wait_starts:
            self._wait_starts[waiting_agent] = time.time()

        return {"ok": True}

    def remove_dependency(self, waiting_agent: str, held_by: str | None = None) -> dict:
        """Remove a dependency edge.

        If *held_by* is None, all outgoing edges from *waiting_agent* are removed.
        """
        if waiting_agent not in self._edges and held_by is None:
            return {"ok": True}  # No-op
        if waiting_agent not in self._edges:
            return {"ok": True}  # No-op

        if held_by is None:
            del self._edges[waiting_agent]
        elif held_by in self._edges[waiting_agent]:
            del self._edges[waiting_agent][held_by]
            if not self._edges[waiting_agent]:
                del self._edges[waiting_agent]
        else:
            return {"ok": True}  # No-op (target doesn't exist)

        # Clear wait start if agent no longer waits for anything
        if waiting_agent not in self._edges or not self._edges[waiting_agent]:
            self._wait_starts.pop(waiting_agent, None)

        return {"ok": True}

    # ── Deadlock Detection (DFS Cycle Detection) ──

    def detect_deadlocks(self) -> list[dict]:
        """Run DFS cycle detection on the dependency graph.

        Returns a list of deadlocks, each with:
        - cycle: list of agent_ids forming the cycle path
        - agents_in_cycle: set of agent_ids
        - description: human-readable string
        """
        # Build adjacency list from _edges
        adj: dict[str, list[str]] = {}
        for waiter, targets in self._edges.items():
            adj[waiter] = list(targets.keys())

        visited: set[str] = set()
        rec_stack: set[str] = set()
        parent: dict[str, str | None] = {}
        deadlocks: list[dict] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in adj.get(node, []):
                # Skip neighbors that are not registered (dangling edges)
                if neighbor not in self._agent_priority:
                    continue
                # Self-loop: agent waiting for itself
                if neighbor == node:
                    cycle = [node, node]
                    deadlocks.append(
                        {
                            "cycle": cycle,
                            "agents_in_cycle": [node],
                            "description": f"Self-loop: {node} is waiting for itself",
                        }
                    )
                    continue

                if neighbor not in visited:
                    parent[neighbor] = node
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found a cycle — reconstruct it
                    cycle = [neighbor]
                    curr = node
                    while curr is not None and curr != neighbor:
                        cycle.append(curr)
                        curr = parent.get(curr)
                    cycle.append(neighbor)  # Close the loop
                    cycle.reverse()

                    deadlocks.append(
                        {
                            "cycle": cycle,
                            "agents_in_cycle": list(dict.fromkeys(cycle)),  # unique, preserve order
                            "description": f"Deadlock detected: {'→'.join(cycle)}",
                        }
                    )

            rec_stack.remove(node)

        # Run DFS from each unvisited node
        for agent in list(adj.keys()):
            if agent not in visited:
                parent[agent] = None
                dfs(agent)

        return deadlocks

    # ── Timeout Detection ──

    def check_timeouts(self) -> list[dict]:
        """Check for agents waiting longer than TIMEOUT_SEC.

        Returns a list of timed-out agents, each with:
        - agent_id, waits_for (list), wait_seconds, timed_out
        """
        now = time.time()
        timeouts: list[dict] = []

        for agent_id, wait_start in list(self._wait_starts.items()):
            # Only check agents that still have active edges
            if agent_id not in self._edges or not self._edges[agent_id]:
                continue
            wait_seconds = now - wait_start
            if wait_seconds > self.TIMEOUT_SEC:
                timeouts.append(
                    {
                        "agent_id": agent_id,
                        "waits_for": list(self._edges[agent_id].keys()),
                        "wait_seconds": int(wait_seconds),
                        "timed_out": True,
                    }
                )

        return timeouts

    # ── Deadlock Resolution (READONLY) ──

    def resolve_deadlock(self, deadlock: dict) -> dict:
        """Suggest a resolution for a detected deadlock (READONLY).

        Finds the lowest-priority agent in the cycle and suggests
        termination with checkpoint-based recovery.
        """
        cycle = deadlock.get("cycle", [])
        if not cycle:
            return {"error": "invalid_deadlock: no cycle"}

        agents_in_cycle = deadlock.get("agents_in_cycle", cycle)
        # Remove duplicates
        unique_agents = list(dict.fromkeys(agents_in_cycle))

        if not unique_agents:
            return {"error": "invalid_deadlock: empty cycle"}

        # Filter to registered agents only
        registered = [a for a in unique_agents if a in self._agent_priority]
        if not registered:
            return {"error": "invalid_deadlock: no registered agents in cycle"}

        # Find lowest priority (highest numerical value)
        terminate = min(registered, key=lambda a: (-self._agent_priority[a], a))

        checkpoint = self._checkpoints.get(terminate)

        return {
            "suggested": True,
            "deadlock_id": "→".join(cycle),
            "agents_in_cycle": registered,
            "terminate_agent": terminate,
            "priority": self._agent_priority[terminate],
            "checkpoint": checkpoint,
            "reason": f"lowest_priority (P{self._agent_priority[terminate]}) in deadlock cycle",
            "message": READONLY_MSG,
        }

    # ── Checkpoint Management ──

    def save_checkpoint(self, agent_id: str, checkpoint: str) -> dict:
        """Record a checkpoint for an agent (for potential recovery)."""
        self._checkpoints[agent_id] = checkpoint
        return {"ok": True}

    def get_checkpoint(self, agent_id: str) -> str | None:
        """Return an agent's last checkpoint, or None."""
        return self._checkpoints.get(agent_id)

    # ── Status Query ──

    def get_status(self, agent_id: str | None = None) -> dict:
        """Return status for one agent or all agents.

        Status includes priority, waiting_for, and checkpoint info.
        """
        if agent_id:
            if agent_id not in self._agent_priority:
                return {"error": "unknown_agent"}

            waiting_for = {}
            if agent_id in self._edges:
                waiting_for = dict(self._edges[agent_id])
            elif self._agent_priority.get(agent_id) is not None:
                waiting_for = {}

            return {
                "agent_id": agent_id,
                "priority": self._agent_priority[agent_id],
                "waiting_for": waiting_for,
                "checkpoint": self._checkpoints.get(agent_id),
            }

        # Return all agents
        result: dict[str, dict] = {}
        for aid in self._agent_priority:
            result[aid] = self.get_status(aid)
        return result

    # ── Cross-layer Feedback ──

    def cross_layer_feedback(self, source: str, severity: str, message: str) -> dict:
        """Receive health alert from another layer (ecos, agora, etc.)."""
        self._alerts.append(
            {
                "source": source,
                "severity": severity,
                "message": message,
                "timestamp": time.time(),
            }
        )
        _log.info("Cross-layer feedback from %s [%s]: %s", source, severity, message)
        return {"ok": True}

    def get_alerts(self, limit: int = 10) -> list[dict]:
        """Return recent cross-layer alerts, newest first."""
        return list(reversed(self._alerts))[:limit]

    # ── MCP Tools (stub) ──

    @staticmethod
    def mcp_tools() -> list[dict]:
        """Return MCP tool definitions."""
        return [
            {
                "name": "metaos_deadlock_check",
                "description": "死锁检测 — 运行 DFS 环检测 + 超时检查，返回所有死锁和超时告警",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "metaos_deadlock_resolve",
                "description": "死锁释放策略 — READONLY，返回建议的终止 Agent 和恢复信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cycle": {
                            "type": "array",
                            "description": "死锁环中的 agent 列表",
                            "items": {"type": "string"},
                        },
                        "agents_in_cycle": {
                            "type": "array",
                            "description": "环中唯一 agent 列表",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["cycle"],
                },
            },
        ]

    def mcp_handle(self, tool_name: str, params: dict) -> dict:
        """Handle MCP tool calls."""
        if tool_name == "metaos_deadlock_check":
            return {
                "deadlocks": self.detect_deadlocks(),
                "timeouts": self.check_timeouts(),
            }
        elif tool_name == "metaos_deadlock_resolve":
            deadlock = params.get("cycle", {})
            return self.resolve_deadlock(deadlock)
        return {"error": f"unknown_tool: {tool_name}"}
