from __future__ import annotations

import json
from pathlib import Path

from metaos_agentkit.capability_runtime import render_claude_settings, render_codex_command
from metaos_agentkit.claude_hook import evaluate


def _repo_stage_policy() -> dict:
    return {
        "name": "repo-stage",
        "codex_sandbox": "workspace-write",
        "codex_approval": "on-request",
        "network": False,
        "isolate_git_worktree": True,
        "allow_explicit_mcp": False,
    }


def test_codex_rendering_enforces_workspace_network_and_mcp_disable() -> None:
    command = render_codex_command(
        policy=_repo_stage_policy(),
        workspace=Path("/tmp/worktree"),
        extra_writable=(),
        disabled_mcp_servers=("browser", "repo-index"),
    )

    assert command[:5] == ["codex", "--cd", "/tmp/worktree", "--sandbox", "workspace-write"]
    assert "--ask-for-approval" in command
    assert "sandbox_workspace_write.network_access=false" in command
    assert 'mcp_servers."browser".enabled=false' in command
    assert 'mcp_servers."repo-index".enabled=false' in command


def test_claude_overlay_fails_closed_and_denies_unapproved_mcp() -> None:
    settings = render_claude_settings(
        policy=_repo_stage_policy(),
        workspace=Path("/tmp/worktree"),
        original_project=Path("/tmp/project"),
        disabled_mcp_servers=("browser",),
    )

    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    assert "mcp__browser__*" in settings["permissions"]["deny"]
    assert "Bash(git push *)" in settings["permissions"]["deny"]
    assert settings["sandbox"]["network"]["allowedDomains"] == []


def test_claude_hook_denies_unapproved_mcp_stage_push_and_outside_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = workspace / "running-session.json"
    session.write_text("{}", encoding="utf-8")
    env = {
        "METAOS_WORKSPACE_ROOT": str(workspace),
        "METAOS_AGENT_SESSION_FILE": str(session),
        "METAOS_MODE": "stage",
        "METAOS_GATE_DECISION": "green",
        "METAOS_ALLOWED_MCP_JSON": '["repo-index"]',
        "METAOS_CAPABILITY_POLICY_JSON": json.dumps({"name": "repo-stage"}),
    }

    denied_mcp = evaluate({"tool_name": "mcp__browser__open", "tool_input": {}}, env)
    denied_push = evaluate({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, env)
    denied_outside_write = evaluate(
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "outside.txt")}}, env
    )

    assert denied_mcp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied_push["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied_outside_write["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_claude_hook_allows_stage_write_inside_isolated_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = workspace / "running-session.json"
    session.write_text("{}", encoding="utf-8")
    target = workspace / "src" / "fix.py"
    env = {
        "METAOS_WORKSPACE_ROOT": str(workspace),
        "METAOS_AGENT_SESSION_FILE": str(session),
        "METAOS_MODE": "stage",
        "METAOS_GATE_DECISION": "green",
        "METAOS_ALLOWED_MCP_JSON": "[]",
        "METAOS_CAPABILITY_POLICY_JSON": json.dumps({"name": "repo-stage"}),
    }

    result = evaluate({"tool_name": "Write", "tool_input": {"file_path": str(target)}}, env)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
