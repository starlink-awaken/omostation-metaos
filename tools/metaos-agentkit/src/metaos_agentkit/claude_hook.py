"""Claude Code PreToolUse hook for MetaOS AgentKit session boundaries."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_MUTATING_GIT_PREFIXES = (
    "git commit",
    "git push",
    "git tag",
    "git reset --hard",
    "git clean",
    "git rebase",
    "git merge",
)
_EXTERNAL_PREFIXES = (
    "gh pr create",
    "gh pr merge",
    "gh release create",
    "curl ",
    "wget ",
)


def _decision(kind: str, reason: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": kind,
    }
    if reason:
        output["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": output}


def _deny(reason: str) -> dict[str, Any]:
    return _decision("deny", reason)


def _ask(reason: str) -> dict[str, Any]:
    return _decision("ask", reason)


def _allow() -> dict[str, Any]:
    return _decision("allow")


def _path_allowed(raw_path: str, workspace: Path) -> bool:
    try:
        candidate = Path(raw_path).expanduser().resolve(strict=False)
        return os.path.commonpath([str(candidate), str(workspace)]) == str(workspace)
    except (OSError, ValueError):
        return False


def _command_is_mutating(command: str) -> bool:
    normalized = " ".join(command.strip().split())
    return normalized.startswith(_MUTATING_GIT_PREFIXES) or normalized.startswith(_EXTERNAL_PREFIXES)


def _tool_path(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name in {"Read", "Write", "Edit"}:
        return str(tool_input.get("file_path", ""))
    if tool_name in {"Glob", "Grep"}:
        return str(tool_input.get("path", ""))
    return ""


def evaluate(payload: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    """Evaluate one Claude PreToolUse payload without provider dependencies."""
    env = env or os.environ
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    try:
        policy = json.loads(env.get("METAOS_CAPABILITY_POLICY_JSON", "{}"))
        allowed_mcp = set(json.loads(env.get("METAOS_ALLOWED_MCP_JSON", "[]")))
    except json.JSONDecodeError:
        return _deny("MetaOS capability policy is invalid; refusing the tool call.")

    workspace_raw = env.get("METAOS_WORKSPACE_ROOT", "")
    if not workspace_raw:
        return _deny("MetaOS workspace root is missing; refusing the tool call.")
    workspace = Path(workspace_raw).expanduser().resolve(strict=False)
    mode = str(env.get("METAOS_MODE", policy.get("mode", "observe")))
    gate = str(env.get("METAOS_GATE_DECISION", policy.get("gate_decision", "red")))
    network = bool(policy.get("network", False))
    profile_name = str(policy.get("name", "core"))
    session_file = env.get("METAOS_AGENT_SESSION_FILE", "")
    if not session_file or not Path(session_file).exists():
        return _deny("MetaOS running-session projection is missing; refusing the tool call.")

    if gate == "red":
        return _deny("MetaOS gate is red; this session is blocked.")
    if tool_name in {"WebFetch", "WebSearch"} and not network:
        return _deny("Web access is not enabled by this MetaOS capability profile.")
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        server = parts[1] if len(parts) > 1 else ""
        if server not in allowed_mcp:
            return _deny(f"MCP server {server!r} is not allowed by this MetaOS capability profile.")
        if profile_name == "external-commit":
            return _ask(f"Confirm MCP tool use for allowed server {server!r} in an external-commit session.")
        return _allow()

    if tool_name in {"Read", "Glob", "Grep"}:
        requested_path = _tool_path(tool_name, tool_input)
        if requested_path and not _path_allowed(requested_path, workspace):
            return _deny(f"{tool_name} target is outside the MetaOS session workspace.")
        return _allow()

    if tool_name in {"Write", "Edit"}:
        file_path = str(tool_input.get("file_path", ""))
        if mode in {"observe", "propose"}:
            return _deny(f"MetaOS mode {mode} is read-only for file mutations.")
        if not _path_allowed(file_path, workspace):
            return _deny("Write/edit target is outside the MetaOS session workspace.")
        return _allow()

    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if mode in {"observe", "propose"} and _command_is_mutating(command):
            return _deny(f"MetaOS mode {mode} does not permit mutating shell commands.")
        if mode == "stage" and _command_is_mutating(command):
            return _deny("MetaOS stage mode prohibits commits, pushes, releases, deployment, and external shell egress.")
        if gate == "yellow" and mode == "commit":
            return _deny("Yellow-gate commit session requires recorded MetaOS approval before tool execution.")
        return _allow()

    return _allow()


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        print(json.dumps(evaluate(payload), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(_deny(f"MetaOS capability hook failed closed: {exc}"), ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
