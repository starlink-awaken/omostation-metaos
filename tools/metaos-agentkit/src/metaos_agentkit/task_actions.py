"""CLI-facing lifecycle actions bound to an explicit AgentKit task record."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import service
from .capability_runtime import render_plan
from .task_store import (
    archive_task as archive_task_projection,
    cleanup_terminal_tasks,
    list_task_records,
    resolve_task_record,
)


def list_tasks(*, project: Path, include_archived: bool = False) -> list[dict[str, Any]]:
    return [record.to_dict() for record in list_task_records(project, include_archived=include_archived)]


def archive_task(*, project: Path, home: Path, task_id: str, apply: bool) -> dict[str, Any]:
    if not task_id:
        raise ValueError("task archive requires --task")
    return archive_task_projection(
        project=project,
        metaos_home=service.metaos_root(home),
        task_id=task_id,
        apply=apply,
    )


def cleanup_tasks(*, project: Path, home: Path, older_than_days: int, apply: bool) -> list[dict[str, Any]]:
    return cleanup_terminal_tasks(
        project=project,
        metaos_home=service.metaos_root(home),
        older_than_days=older_than_days,
        apply=apply,
    )


def approve_task(*, project: Path, home: Path, task_id: str | None, comment: str = "") -> Path:
    return _transition(project=project, home=home, task_id=task_id, action="approve", output_name="approved-session.json", comment=comment)


def reject_task(*, project: Path, home: Path, task_id: str | None, comment: str = "") -> Path:
    return _transition(project=project, home=home, task_id=task_id, action="reject", output_name="rejected-session.json", comment=comment)


def _transition(*, project: Path, home: Path, task_id: str | None, action: str, output_name: str, comment: str) -> Path:
    record = resolve_task_record(project, task_id=task_id)
    output = record.directory / output_name
    result = service._run_bridge(
        project=project,
        home=home,
        arguments=[action, "--session-file", str(record.session_file), "--out", str(output), "--comment", comment],
    )
    if result.returncode != 0:
        raise ValueError(service._bridge_error(result))
    return output


def finalize_task(
    *,
    project: Path,
    home: Path,
    task_id: str | None,
    summary: str,
    evidence: list[str],
    verification_passed: bool,
) -> Path:
    record = resolve_task_record(project, task_id=task_id)
    output = record.directory / "final-session.json"
    args = ["finalize", "--session-file", str(record.session_file), "--out", str(output), "--summary", summary]
    for item in evidence:
        args.extend(["--evidence", item])
    if verification_passed:
        args.append("--verification-passed")
    result = service._run_bridge(project=project, home=home, arguments=args)
    if result.returncode not in {0, 4}:
        raise ValueError(service._bridge_error(result))
    return output


def launch_task(
    *,
    provider: str,
    project: Path,
    home: Path,
    task_id: str | None,
    mode: str | None,
    provider_args: list[str],
    execute: bool,
) -> int:
    if provider not in {"codex", "claude"}:
        raise ValueError("provider must be codex or claude")
    service._validate_provider_args(provider, provider_args)
    project = project.resolve()
    record = resolve_task_record(project, task_id=task_id)
    session_file = record.session_file
    session = service._load_session(session_file)
    status = str(session.get("status", ""))
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
                    "task_id": record.task_id,
                    "provider": provider,
                    "provider_args": provider_args,
                    "bridge_command": [
                        *service._runtime_command(project),
                        "--data-dir",
                        str(service.metaos_root(home) / "data"),
                        "prepare",
                        "--session-file",
                        str(session_file),
                    ],
                    "capability_profile": session.get("capability", {}).get("profile"),
                    "requested_mcp_servers": [
                        item.removeprefix("mcp:")
                        for item in session.get("capability", {}).get("requested", [])
                        if item.startswith("mcp:")
                    ],
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
        context_result = service._run_bridge(project=project, home=home, arguments=["context", "--session-file", str(prepared_file)])
        if context_result.returncode != 0:
            service._emit_bridge_result(context_result)
            return context_result.returncode
        context = service._parse_bridge_payload(context_result.stdout)
        prepared_session = context["session"]
    else:
        prepared_file = record.directory / "prepared-session.json"
        prepared_result = service._run_bridge(
            project=project,
            home=home,
            arguments=["prepare", "--session-file", str(session_file), "--out", str(prepared_file)],
        )
        if prepared_result.returncode != 0:
            service._emit_bridge_result(prepared_result)
            return prepared_result.returncode
        context = service._parse_bridge_payload(prepared_result.stdout)
        prepared_session = context["session"]
        service._save_prepared_context(prepared_file, context)
        if prepared_session["status"] == "blocked":
            service._emit_bridge_result(prepared_result)
            return 3

    capability_policy = context.get("capability_policy")
    launch_context = context.get("launch_context") or {}
    if not isinstance(capability_policy, dict):
        raise ValueError("Prepared session is missing its resolved capability policy. Create a new task.")
    runtime_plan = render_plan(
        provider=provider,
        project=project,
        task_dir=record.directory,
        metaos_home=service.metaos_root(home),
        session=prepared_session,
        policy=capability_policy,
    )

    running = record.directory / "running-session.json"
    running_result = service._run_bridge(
        project=project,
        home=home,
        arguments=["mark-running", "--session-file", str(prepared_file), "--out", str(running)],
    )
    if running_result.returncode != 0:
        service._emit_bridge_result(running_result)
        return running_result.returncode

    env = os.environ.copy()
    env.update(launch_context.get("environment", {}))
    env.update(runtime_plan.environment)
    env["METAOS_PROJECT_ROOT"] = str(project)
    env["METAOS_AGENT_SESSION_FILE"] = str(running)
    env["METAOS_AGENTKIT_HOME"] = str(service.global_home(home))
    command = [*runtime_plan.command_prefix, *provider_args]
    service._write_launch_audit(record.directory, runtime_plan, command)
    try:
        result = subprocess.run(command, cwd=runtime_plan.working_directory, env=env, check=False)
    except FileNotFoundError:
        print(f"Provider command not found: {provider}", file=sys.stderr)
        service._write_provider_exit(record.directory, returncode=127, detail="provider command not found")
        return 127
    service._write_provider_exit(
        record.directory,
        returncode=result.returncode,
        detail="provider exited; session still requires explicit finalize",
    )
    return result.returncode
