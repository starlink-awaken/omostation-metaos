"""Filesystem projections and provider launching for MetaOS AgentKit.

AgentKit is a provider adapter. Canonical authorization, session state,
decisions, assets, and traces belong to the root MetaOS runtime.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .capability_runtime import ProviderRuntimePlan, render_plan
from .templates import CLAUDE_BLOCK, CODEX_BLOCK, CORE_POLICY, MARKER_BEGIN, MARKER_END, SKILLS


@dataclass(frozen=True)
class Plan:
    action: str
    target: Path
    detail: str


def metaos_root(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".metaos"


def global_home(home: Path | None = None) -> Path:
    """AgentKit-owned global state, nested below the MetaOS root."""
    return metaos_root(home) / "agentkit"


def project_home(project: Path) -> Path:
    """AgentKit-owned project state, nested below the MetaOS project root."""
    return project / ".metaos" / "agentkit"


def normalize_providers(raw: str) -> tuple[str, ...]:
    providers = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    unknown = sorted(set(providers) - {"codex", "claude"})
    if unknown:
        raise ValueError(f"Unsupported provider(s): {', '.join(unknown)}")
    if not providers:
        raise ValueError("At least one provider is required.")
    return tuple(dict.fromkeys(providers))


def _replace_marked_block(existing: str, block: str) -> str:
    start = existing.find(MARKER_BEGIN)
    if start == -1:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        return f"{existing}{separator}\n{block}"
    end = existing.find(MARKER_END, start)
    if end == -1:
        raise ValueError("Found a MetaOS marker begin without its end marker; refusing to overwrite.")
    end += len(MARKER_END)
    suffix = existing[end:]
    if suffix.startswith("\n"):
        suffix = suffix[1:]
    return f"{existing[:start]}{block}{suffix}"


def _remove_marked_block(existing: str) -> str:
    start = existing.find(MARKER_BEGIN)
    if start == -1:
        return existing
    end = existing.find(MARKER_END, start)
    if end == -1:
        raise ValueError("Found a MetaOS marker begin without its end marker; refusing to overwrite.")
    end += len(MARKER_END)
    if end < len(existing) and existing[end] == "\n":
        end += 1
    return existing[:start].rstrip() + ("\n" if existing[:start].strip() else "") + existing[end:]


def _backup(path: Path, agentkit_home: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = agentkit_home / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_name = path.as_posix().replace("/", "__").replace("~", "home")
    candidate = backup_dir / f"{safe_name}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.bak"
    shutil.copy2(path, candidate)
    return candidate


def _write_text(path: Path, content: str, apply: bool, plans: list[Plan], action: str = "write") -> None:
    plans.append(Plan(action, path, f"{len(content.encode('utf-8'))} bytes"))
    if not apply:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _inject(path: Path, block: str, agentkit_home: Path, apply: bool, plans: list[Plan]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    proposed = _replace_marked_block(existing, block)
    if proposed == existing:
        plans.append(Plan("unchanged", path, "managed block already current"))
        return
    plans.append(Plan("inject", path, "replace or append marker-bounded MetaOS block"))
    if not apply:
        return
    _backup(path, agentkit_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proposed, encoding="utf-8")


def _symlink(source: Path, target: Path, apply: bool, plans: list[Plan]) -> None:
    if target.is_symlink() and target.resolve() == source.resolve():
        plans.append(Plan("unchanged", target, "correct skill symlink already exists"))
        return
    if target.exists() or target.is_symlink():
        plans.append(Plan("skip", target, "path exists and is not managed by MetaOS AgentKit"))
        return
    plans.append(Plan("link", target, f"-> {source}"))
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)


def install_global(*, home: Path, providers: Iterable[str], apply: bool) -> list[Plan]:
    agentkit_home = global_home(home)
    plans: list[Plan] = []
    _write_text(agentkit_home / "core" / "METAOS-CORE.md", CORE_POLICY, apply, plans)
    for name, skill in SKILLS.items():
        _write_text(agentkit_home / "skills" / name / "SKILL.md", skill, apply, plans)

    for provider in providers:
        if provider == "codex":
            _inject(home / ".codex" / "AGENTS.md", CODEX_BLOCK, agentkit_home, apply, plans)
            skill_root = home / ".agents" / "skills"
        else:
            _inject(home / ".claude" / "CLAUDE.md", CLAUDE_BLOCK, agentkit_home, apply, plans)
            skill_root = home / ".claude" / "skills"
        for name in SKILLS:
            _symlink(agentkit_home / "skills" / name, skill_root / name, apply, plans)
    return plans


def _append_git_exclude(project: Path, apply: bool, plans: list[Plan]) -> None:
    target = project / ".git" / "info" / "exclude"
    if not (project / ".git").exists():
        plans.append(Plan("skip", target, "not a Git worktree; no local exclude update"))
        return
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    line = ".metaos/"
    if line in {entry.strip() for entry in existing.splitlines()}:
        plans.append(Plan("unchanged", target, "already excludes .metaos/"))
        return
    content = f"{existing.rstrip()}\n# MetaOS AgentKit local state\n{line}\n"
    _write_text(target, content, apply, plans, action="append")


def install_local(*, project: Path, home: Path, providers: Iterable[str], apply: bool) -> list[Plan]:
    project = project.resolve()
    agentkit_home = global_home(home)
    local_home = project_home(project)
    plans: list[Plan] = []
    for folder in ("tasks", "staging", "audit", "quarantine"):
        path = local_home / folder
        plans.append(Plan("mkdir", path, "AgentKit provider-local projection directory"))
        if apply:
            path.mkdir(parents=True, exist_ok=True)
    _append_git_exclude(project, apply, plans)

    for provider in providers:
        if provider == "codex":
            _inject(project / "AGENTS.md", CODEX_BLOCK, agentkit_home, apply, plans)
            skill_root = project / ".agents" / "skills"
        else:
            _inject(project / "CLAUDE.local.md", CLAUDE_BLOCK, agentkit_home, apply, plans)
            skill_root = project / ".claude" / "skills"
        for name in SKILLS:
            _symlink(agentkit_home / "skills" / name, skill_root / name, apply, plans)
    return plans


def uninstall_global(*, home: Path, providers: Iterable[str], apply: bool) -> list[Plan]:
    agentkit_home = global_home(home)
    plans: list[Plan] = []
    targets = {
        "codex": (home / ".codex" / "AGENTS.md", home / ".agents" / "skills"),
        "claude": (home / ".claude" / "CLAUDE.md", home / ".claude" / "skills"),
    }
    for provider in providers:
        instruction, skill_root = targets[provider]
        if instruction.exists():
            existing = instruction.read_text(encoding="utf-8")
            updated = _remove_marked_block(existing)
            if updated != existing:
                plans.append(Plan("remove", instruction, "managed MetaOS block"))
                if apply:
                    _backup(instruction, agentkit_home)
                    instruction.write_text(updated, encoding="utf-8")
        for name in SKILLS:
            link = skill_root / name
            if link.is_symlink() and link.resolve() == (agentkit_home / "skills" / name).resolve():
                plans.append(Plan("unlink", link, "managed skill symlink"))
                if apply:
                    link.unlink()
    return plans


def status(*, project: Path, home: Path) -> dict[str, object]:
    agentkit_home = global_home(home)
    project = project.resolve()
    return {
        "metaos_root": str(metaos_root(home)),
        "agentkit_home": str(agentkit_home),
        "global_core_exists": (agentkit_home / "core" / "METAOS-CORE.md").exists(),
        "project": str(project),
        "agentkit_project_exists": project_home(project).exists(),
        "codex_global_marker": _has_marker(home / ".codex" / "AGENTS.md"),
        "claude_global_marker": _has_marker(home / ".claude" / "CLAUDE.md"),
        "codex_project_marker": _has_marker(project / "AGENTS.md"),
        "claude_project_marker": _has_marker(project / "CLAUDE.local.md"),
        "runtime_bridge": _runtime_command(project),
    }


def _has_marker(path: Path) -> bool:
    return path.exists() and MARKER_BEGIN in path.read_text(encoding="utf-8")


def create_task(
    *,
    project: Path,
    description: str,
    risk: str,
    mode: str,
    capability_profile: str | None = None,
    allowed_mcp_servers: Iterable[str] = (),
    apply: bool = True,
) -> Path:
    valid_risks = {"R0", "R1", "R2", "R3", "R4"}
    valid_modes = {"observe", "propose", "stage", "commit"}
    if risk not in valid_risks:
        raise ValueError(f"risk must be one of {', '.join(sorted(valid_risks))}")
    if mode not in valid_modes:
        raise ValueError(f"mode must be one of {', '.join(sorted(valid_modes))}")
    task_id = f"task-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    task_dir = project_home(project.resolve()) / "tasks" / task_id
    profile = capability_profile or _default_profile(risk=risk, mode=mode)
    requested = [f"mcp:{name}" for name in dict.fromkeys(name.strip() for name in allowed_mcp_servers if name.strip())]
    payload = {
        "session_id": f"agent-{uuid4().hex[:16]}",
        "task_id": task_id,
        "h_id": "",
        "provider": "generic",
        "description": description,
        "risk": risk,
        "mode": mode,
        "gate_decision": "green",
        "gate_reason": "",
        "confirmation_status": "not_required",
        "capability": {"profile": profile, "requested": requested, "denied": []},
        "scope": [],
        "exclusions": ["git commit", "git push", "deployment"],
        "success_criteria": [],
        "stop_conditions": ["same approach fails twice without new evidence"],
        "verification": {"commands": [], "expected_outcomes": [], "notes": []},
        "rollback_or_containment": ["keep changes staged or reviewable before commit"],
        "status": "prepared",
        "created_at": datetime.now(UTC).isoformat(),
        "finalized_at": None,
        "result_summary": "",
        "evidence": [],
        "decision_id": "",
        "asset_id": "",
    }
    target = task_dir / "agent-session.json"
    if apply:
        task_dir.mkdir(parents=True, exist_ok=False)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def approve_task(*, project: Path, home: Path, comment: str = "") -> Path:
    return _session_transition(project=project, home=home, action="approve", output_name="approved-session.json", comment=comment)


def reject_task(*, project: Path, home: Path, comment: str = "") -> Path:
    return _session_transition(project=project, home=home, action="reject", output_name="rejected-session.json", comment=comment)


def _session_transition(*, project: Path, home: Path, action: str, output_name: str, comment: str) -> Path:
    session_file = _latest_session(project)
    if not session_file:
        raise ValueError("No AgentKit session found. Run task new first.")
    output = session_file.parent / output_name
    result = _run_bridge(
        project=project,
        home=home,
        arguments=[action, "--session-file", str(session_file), "--out", str(output), "--comment", comment],
    )
    if result.returncode != 0:
        raise ValueError(_bridge_error(result))
    return output


def launch(*, provider: str, project: Path, home: Path, mode: str | None, provider_args: list[str], execute: bool) -> int:
    if provider not in {"codex", "claude"}:
        raise ValueError("provider must be codex or claude")
    _validate_provider_args(provider, provider_args)
    project = project.resolve()
    session_file = _latest_session(project)
    if not session_file:
        raise ValueError("No AgentKit session found. Run task new first.")
    session = _load_session(session_file)
    status = session.get("status", "")
    if status in {"finalized", "failed", "cancelled"}:
        raise ValueError(f"Cannot launch a {status} session. Create a new task.")

    governed = bool(session.get("decision_id") and session.get("asset_id"))
    if governed:
        if mode and mode != session.get("mode"):
            raise ValueError("Cannot change mode after MetaOS governance. Create a new task.")
        if session.get("provider") not in {"generic", provider}:
            raise ValueError("Cannot change provider after MetaOS governance. Create a new task.")
    else:
        if mode:
            session["mode"] = mode
        session["provider"] = provider
        session_file.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not execute:
        print(
            json.dumps(
                {
                    "provider": provider,
                    "provider_args": provider_args,
                    "bridge_command": [*_runtime_command(project), "--data-dir", str(metaos_root(home) / "data"), "prepare", "--session-file", str(session_file)],
                    "capability_profile": session.get("capability", {}).get("profile"),
                    "requested_mcp_servers": [item.removeprefix("mcp:") for item in session.get("capability", {}).get("requested", []) if item.startswith("mcp:")],
                    "session_file": str(session_file),
                    "note": "Preview only: no gate evaluation, worktree creation, policy write, or provider launch occurred.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if governed:
        if session.get("status") == "blocked":
            raise ValueError("Session is blocked. Approve/reject the pending MetaOS session before launch.")
        if session.get("status") != "prepared":
            raise ValueError(f"Session must be prepared before launch; current status is {session.get('status')}.")
        prepared_file = session_file
        prepared_session = session
        context = _load_prepared_context(prepared_file)
    else:
        prepared_file = session_file.parent / "prepared-session.json"
        prepared_result = _run_bridge(
            project=project,
            home=home,
            arguments=["prepare", "--session-file", str(session_file), "--out", str(prepared_file)],
        )
        if prepared_result.returncode != 0:
            _emit_bridge_result(prepared_result)
            return prepared_result.returncode
        payload = _parse_bridge_payload(prepared_result.stdout)
        prepared_session = payload["session"]
        if prepared_session["status"] == "blocked":
            _save_prepared_context(prepared_file, payload)
            _emit_bridge_result(prepared_result)
            return 3
        _save_prepared_context(prepared_file, payload)
        context = payload

    capability_policy = context.get("capability_policy")
    launch_context = context.get("launch_context") or {}
    if not isinstance(capability_policy, dict):
        raise ValueError("Prepared session is missing its resolved capability policy. Create a new task.")
    runtime_plan = render_plan(
        provider=provider,
        project=project,
        task_dir=prepared_file.parent,
        metaos_home=metaos_root(home),
        session=prepared_session,
        policy=capability_policy,
    )

    running = prepared_file.parent / "running-session.json"
    running_result = _run_bridge(
        project=project,
        home=home,
        arguments=["mark-running", "--session-file", str(prepared_file), "--out", str(running)],
    )
    if running_result.returncode != 0:
        _emit_bridge_result(running_result)
        return running_result.returncode

    env = os.environ.copy()
    env.update(launch_context.get("environment", {}))
    env.update(runtime_plan.environment)
    env["METAOS_PROJECT_ROOT"] = str(project)
    env["METAOS_AGENT_SESSION_FILE"] = str(running)
    env["METAOS_AGENTKIT_HOME"] = str(global_home(home))
    command = [*runtime_plan.command_prefix, *provider_args]
    _write_launch_audit(prepared_file.parent, runtime_plan, command)
    try:
        result = subprocess.run(command, cwd=runtime_plan.working_directory, env=env, check=False)
    except FileNotFoundError:
        print(f"Provider command not found: {provider}", file=sys.stderr)
        _write_provider_exit(prepared_file.parent, returncode=127, detail="provider command not found")
        return 127
    _write_provider_exit(prepared_file.parent, returncode=result.returncode, detail="provider exited; session still requires explicit finalize")
    return result.returncode


def finalize_task(
    *,
    project: Path,
    home: Path,
    summary: str,
    evidence: list[str],
    verification_passed: bool,
) -> Path:
    session_file = _latest_session(project)
    if not session_file:
        raise ValueError("No AgentKit session found. Run task new first.")
    output = session_file.parent / "final-session.json"
    args = ["finalize", "--session-file", str(session_file), "--out", str(output), "--summary", summary]
    for item in evidence:
        args.extend(["--evidence", item])
    if verification_passed:
        args.append("--verification-passed")
    result = _run_bridge(project=project, home=home, arguments=args)
    if result.returncode not in {0, 4}:
        raise ValueError(_bridge_error(result))
    return output


def _default_profile(*, risk: str, mode: str) -> str:
    if risk == "R2" and mode == "stage":
        return "repo-stage"
    if risk in {"R3", "R4"} and mode == "commit":
        return "external-commit"
    if risk == "R1":
        return "repo-read"
    return "core"


def _latest_session(project: Path) -> Path | None:
    tasks = project_home(project.resolve()) / "tasks"
    if not tasks.exists():
        return None
    names = ("running-session.json", "approved-session.json", "prepared-session.json", "agent-session.json")
    candidates = [path for name in names for path in tasks.glob(f"*/{name}")]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _load_session(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _context_path(session_file: Path) -> Path:
    return session_file.parent / "runtime" / "prepared-context.json"


def _save_prepared_context(session_file: Path, payload: dict) -> Path:
    target = _context_path(session_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _load_prepared_context(session_file: Path) -> dict:
    target = _context_path(session_file)
    if not target.exists():
        raise ValueError("Prepared session has no persisted MetaOS context. Create a new task.")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Prepared MetaOS context is invalid; create a new task.") from exc


def _validate_provider_args(provider: str, provider_args: list[str]) -> None:
    blocked = {
        "codex": {
            "--sandbox",
            "-s",
            "--ask-for-approval",
            "-a",
            "--add-dir",
            "--config",
            "-c",
            "--profile",
            "-p",
            "--permissions-profile",
            "-P",
            "--dangerously-bypass-approvals-and-sandbox",
            "--yolo",
        },
        "claude": {
            "--settings",
            "--permission-mode",
            "--dangerously-skip-permissions",
            "--bypass-permissions",
        },
    }[provider]
    for arg in provider_args:
        if arg in blocked or any(arg.startswith(f"{item}=") for item in blocked if item.startswith("--")):
            raise ValueError(f"Provider argument {arg!r} can weaken or replace the MetaOS capability boundary.")


def _write_launch_audit(task_dir: Path, runtime_plan: ProviderRuntimePlan, command: list[str]) -> None:
    target = task_dir / "audit" / "launch-plan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "provider": runtime_plan.provider,
                "working_directory": str(runtime_plan.working_directory),
                "worktree_path": str(runtime_plan.worktree_path) if runtime_plan.worktree_path else None,
                "policy_file": str(runtime_plan.policy_file) if runtime_plan.policy_file else None,
                "allowed_mcp_servers": list(runtime_plan.allowed_mcp_servers),
                "disabled_mcp_servers": list(runtime_plan.disabled_mcp_servers),
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_provider_exit(task_dir: Path, *, returncode: int, detail: str) -> None:
    target = task_dir / "audit" / "provider-exit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "returncode": returncode,
                "detail": detail,
                "finalization_required": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _runtime_command(project: Path) -> list[str]:
    configured = os.environ.get("METAOS_AGENT_RUNTIME_COMMAND", "").strip()
    if configured:
        return shlex.split(configured)
    configured_root = os.environ.get("METAOS_RUNTIME_ROOT", "").strip()
    candidates = [Path(configured_root)] if configured_root else []
    candidates.extend([project.resolve(), *project.resolve().parents, *Path(__file__).resolve().parents])
    for candidate in candidates:
        if (candidate / "src" / "metaos" / "agent_cli.py").is_file() and (candidate / "pyproject.toml").is_file():
            return ["uv", "run", "--directory", str(candidate), "python", "-m", "metaos.agent_cli"]
    return ["metaos-agent"]


def _run_bridge(*, project: Path, home: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    command = [*_runtime_command(project), "--data-dir", str(metaos_root(home) / "data"), *arguments]
    try:
        return subprocess.run(command, cwd=project, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ValueError(
            "MetaOS runtime bridge was not found. Run AgentKit from an omostation-metaos checkout, "
            "set METAOS_RUNTIME_ROOT, or set METAOS_AGENT_RUNTIME_COMMAND."
        ) from exc


def _parse_bridge_payload(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MetaOS runtime bridge returned invalid JSON: {stdout[:300]}") from exc


def _bridge_error(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "MetaOS runtime bridge failed").strip()


def _emit_bridge_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
