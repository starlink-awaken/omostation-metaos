"""Provider-specific enforcement projections for canonical MetaOS policies.

This module never decides whether a session is authorized. It consumes the
policy emitted by `metaos-agent prepare` and produces command flags, temporary
settings, worktree isolation, and MCP-deny overlays for one provider session.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SECRET_READ_DENIES = [
    "~/.ssh/**",
    "~/.gnupg/**",
    "~/.aws/**",
    "~/.config/gcloud/**",
    "~/.kube/**",
    "~/.local/share/keyrings/**",
    "./.env",
    "./.env.*",
    "./secrets/**",
    "./config/credentials.json",
]


@dataclass(frozen=True)
class ProviderRuntimePlan:
    provider: str
    command_prefix: list[str]
    environment: dict[str, str]
    working_directory: Path
    policy_file: Path | None
    worktree_path: Path | None
    disabled_mcp_servers: tuple[str, ...]
    allowed_mcp_servers: tuple[str, ...]


def allowed_mcp_servers(policy: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(name) for name in policy.get("allowed_mcp_servers", []) if str(name)))


def ensure_stage_worktree(*, project: Path, metaos_home: Path, session_id: str) -> Path:
    """Create or reuse a detached Git worktree for an R2 stage session.

    The worktree is outside the original checkout and starts at HEAD. Existing
    uncommitted work stays in the user's checkout and is intentionally not
    copied into the agent workspace.
    """
    root = _git_root(project)
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    target = metaos_home / "agentkit" / "worktrees" / digest / session_id
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(target), "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"Could not create isolated stage worktree: {(result.stderr or result.stdout).strip()}")
    return target


def render_plan(
    *,
    provider: str,
    project: Path,
    task_dir: Path,
    metaos_home: Path,
    session: dict[str, Any],
    policy: dict[str, Any],
    inherited_env: dict[str, str] | None = None,
) -> ProviderRuntimePlan:
    """Materialize one capability policy for one Provider launch."""
    provider = provider.lower()
    if provider not in {"codex", "claude"}:
        raise ValueError("provider must be codex or claude")
    if session.get("status") not in {"prepared", "running"}:
        raise ValueError(f"Session is not launchable from status {session.get('status')!r}.")
    if session.get("status") == "prepared" and session.get("gate_decision") == "yellow" and session.get("confirmation_status") != "approved":
        raise ValueError("Yellow-gate session requires recorded human approval before launch.")

    project = project.resolve()
    metaos_home = metaos_home.resolve()
    isolate = bool(policy.get("isolate_git_worktree"))
    worktree = ensure_stage_worktree(project=project, metaos_home=metaos_home, session_id=session["session_id"]) if isolate else None
    working_directory = worktree or project
    runtime_dir = task_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    allowed = allowed_mcp_servers(policy)
    environment = dict(inherited_env or os.environ)
    environment.update(
        {
            "METAOS_AGENT_SESSION_FILE": str(task_dir / "prepared-session.json"),
            "METAOS_AGENT_SESSION_ID": session["session_id"],
            "METAOS_WORKSPACE_ROOT": str(working_directory),
            "METAOS_ORIGINAL_PROJECT_ROOT": str(project),
            "METAOS_ALLOWED_MCP_JSON": json.dumps(list(allowed)),
            "METAOS_CAPABILITY_POLICY_JSON": json.dumps(policy, sort_keys=True),
        }
    )

    if provider == "codex":
        disabled = tuple(sorted(set(discover_codex_mcp_servers(home=Path.home())) - set(allowed)))
        prefix = render_codex_command(
            policy=policy,
            workspace=working_directory,
            extra_writable=(),
            disabled_mcp_servers=disabled,
        )
        policy_file = runtime_dir / "codex-policy.json"
        policy_file.write_text(
            json.dumps(
                {
                    "provider": "codex",
                    "workspace": str(working_directory),
                    "worktree": str(worktree) if worktree else None,
                    "allowed_mcp_servers": list(allowed),
                    "disabled_mcp_servers": list(disabled),
                    "command_prefix": prefix,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return ProviderRuntimePlan(
            provider="codex",
            command_prefix=prefix,
            environment=environment,
            working_directory=working_directory,
            policy_file=policy_file,
            worktree_path=worktree,
            disabled_mcp_servers=disabled,
            allowed_mcp_servers=allowed,
        )

    disabled = tuple(sorted(set(discover_claude_mcp_servers(home=Path.home(), project=project)) - set(allowed)))
    settings_path = runtime_dir / "claude-settings.json"
    settings_path.write_text(
        json.dumps(
            render_claude_settings(
                policy=policy,
                workspace=working_directory,
                original_project=project,
                disabled_mcp_servers=disabled,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    permission_mode = "plan" if session.get("mode") in {"observe", "propose"} else "default"
    return ProviderRuntimePlan(
        provider="claude",
        command_prefix=["claude", "--settings", str(settings_path), "--permission-mode", permission_mode],
        environment=environment,
        working_directory=working_directory,
        policy_file=settings_path,
        worktree_path=worktree,
        disabled_mcp_servers=disabled,
        allowed_mcp_servers=allowed,
    )


def render_codex_command(
    *,
    policy: dict[str, Any],
    workspace: Path,
    extra_writable: tuple[Path, ...],
    disabled_mcp_servers: tuple[str, ...],
) -> list[str]:
    """Return enforced Codex CLI arguments without shell quoting."""
    command = [
        "codex",
        "--cd",
        str(workspace),
        "--sandbox",
        str(policy["codex_sandbox"]),
        "--ask-for-approval",
        str(policy["codex_approval"]),
        "--config",
        f"sandbox_workspace_write.network_access={'true' if policy.get('network') else 'false'}",
        "--config",
        "sandbox_workspace_write.exclude_slash_tmp=true",
        "--config",
        "sandbox_workspace_write.exclude_tmpdir_env_var=true",
    ]
    for path in extra_writable:
        command.extend(["--add-dir", str(path)])
    for server in disabled_mcp_servers:
        command.extend(["--config", f'mcp_servers.{_toml_key(server)}.enabled=false'])
    return command


def render_claude_settings(
    *,
    policy: dict[str, Any],
    workspace: Path,
    original_project: Path,
    disabled_mcp_servers: tuple[str, ...],
) -> dict[str, Any]:
    """Render a session-only Claude settings overlay.

    Deny rules are intentional because Claude merges allow arrays across
    scopes. This overlay therefore blocks sensitive paths, explicitly denied
    MCP servers, destructive Git commands in stage/read modes, and tool calls
    rejected by the PreToolUse hook.
    """
    mode = str(policy.get("name", "core"))
    deny = [
        "Read(./.env)",
        "Read(./.env.*)",
        "Read(./secrets/**)",
        "Read(./config/credentials.json)",
    ]
    deny.extend(f"mcp__{server}__*" for server in disabled_mcp_servers)
    if mode != "external-commit":
        deny.extend(
            [
                "Bash(git commit *)",
                "Bash(git push *)",
                "Bash(git tag *)",
                "Bash(gh pr create *)",
                "Bash(gh pr merge *)",
                "Bash(gh release create *)",
            ]
        )
    return {
        "permissions": {"deny": deny},
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": False,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "allowWrite": [str(workspace)],
                "denyWrite": [str(original_project)] if workspace != original_project else [],
                "denyRead": _SECRET_READ_DENIES,
            },
            "network": {
                "allowedDomains": [],
                "allowLocalBinding": False,
            },
        },
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{sys.executable} -m metaos_agentkit.claude_hook",
                        }
                    ]
                }
            ]
        },
    }


def discover_codex_mcp_servers(*, home: Path) -> set[str]:
    config = home / ".codex" / "config.toml"
    if not config.exists():
        return set()
    try:
        payload = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    servers = payload.get("mcp_servers") or {}
    return {str(name) for name in servers if isinstance(name, str)}


def discover_claude_mcp_servers(*, home: Path, project: Path) -> set[str]:
    names: set[str] = set()
    for path in (home / ".claude.json", project / ".mcp.json"):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = payload.get("mcpServers") or {}
        if isinstance(servers, dict):
            names.update(str(name) for name in servers)
    return names


def _git_root(project: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("The repo-stage capability profile requires a Git worktree.")
    return Path(result.stdout.strip()).resolve()


def _toml_key(value: str) -> str:
    """Render a safe TOML quoted key for CLI config overrides."""
    return json.dumps(value)
