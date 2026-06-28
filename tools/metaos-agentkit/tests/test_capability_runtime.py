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


def test_codex_rendering_enforces_workspace_network_web_and_mcp_disable() -> None:
    command = render_codex_command(
        policy=_repo_stage_policy(),
        workspace=Path("/tmp/worktree"),
        extra_writable=(),
        disabled_mcp_servers=("browser", "repo-index"),
        allowed_mcp_servers=("docs",),
    )

    assert command[:5] == ["codex", "--cd", "/tmp/worktree", "--sandbox", "workspace-write"]
    assert "--ask-for-approval" in command
    assert "sandbox_workspace_write.network_access=false" in command
    assert "tools.web_search=false" in command
    assert 'mcp_servers."browser".enabled=false' in command
    assert 'mcp_servers."repo-index".enabled=false' in command
    assert 'mcp_servers."docs".default_tools_approval_mode="prompt"' in command


def test_claude_overlay_fails_closed_and_denies_unapproved_mcp_and_web() -> None:
    settings = render_claude_settings(
        policy=_repo_stage_policy(),
        workspace=Path("/tmp/worktree"),
        original_project=Path("/tmp/project"),
        disabled_mcp_servers=("browser",),
    )

    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    assert settings["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert settings["disableClaudeAiConnectors"] is True
    assert settings["disabledMcpjsonServers"] == ["browser"]
    assert "mcp__browser__*" in settings["permissions"]["deny"]
    assert "WebFetch" in settings["permissions"]["deny"]
    assert "WebSearch" in settings["permissions"]["deny"]
    assert "Bash(git push *)" in settings["permissions"]["deny"]
    assert settings["sandbox"]["network"]["allowedDomains"] == []


def test_claude_hook_denies_unapproved_mcp_stage_push_web_and_outside_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = workspace / "running-session.json"
    session.write_text("{}", encoding="utf-8")
    env = {
        "METAOS_WORKSPACE_ROOT": str(workspace),
        "METAOS_AGENT_SESSION_FILE": str(session),
        "METAOS_MODE": "stage",
        "METAOS_GATE_DECISION": "green",
        "METAOS_ALLOWED_MCP_TOOLS_JSON": '{"repo-index":["*"]}',
        "METAOS_CAPABILITY_POLICY_JSON": json.dumps({"name": "repo-stage", "network": False}),
    }

    denied_mcp = evaluate({"tool_name": "mcp__browser__open", "tool_input": {}}, env)
    denied_push = evaluate({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, env)
    denied_web = evaluate({"tool_name": "WebFetch", "tool_input": {"url": "https://example.com"}}, env)
    denied_outside_write = evaluate(
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "outside.txt")}}, env
    )
    denied_outside_read = evaluate(
        {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "outside.txt")}}, env
    )

    assert denied_mcp["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied_push["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied_web["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied_outside_write["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert denied_outside_read["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_claude_hook_allows_only_the_named_mcp_tool_and_asks_for_external_commit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = workspace / "running-session.json"
    session.write_text("{}", encoding="utf-8")
    env = {
        "METAOS_WORKSPACE_ROOT": str(workspace),
        "METAOS_AGENT_SESSION_FILE": str(session),
        "METAOS_MODE": "commit",
        "METAOS_GATE_DECISION": "green",
        "METAOS_ALLOWED_MCP_TOOLS_JSON": '{"calendar":["create_event"]}',
        "METAOS_CAPABILITY_POLICY_JSON": json.dumps({"name": "external-commit", "network": False}),
    }

    allowed = evaluate({"tool_name": "mcp__calendar__create_event", "tool_input": {}}, env)
    denied = evaluate({"tool_name": "mcp__calendar__delete_event", "tool_input": {}}, env)

    assert allowed["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


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
        "METAOS_ALLOWED_MCP_TOOLS_JSON": "{}",
        "METAOS_CAPABILITY_POLICY_JSON": json.dumps({"name": "repo-stage", "network": False}),
    }

    result = evaluate({"tool_name": "Write", "tool_input": {"file_path": str(target)}}, env)

    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
