"""Filesystem operations for MetaOS AgentKit."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .templates import CLAUDE_BLOCK, CODEX_BLOCK, CORE_POLICY, MARKER_BEGIN, MARKER_END, SKILLS


@dataclass(frozen=True)
class Plan:
    action: str
    target: Path
    detail: str


def global_home(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".metaos"


def project_home(project: Path) -> Path:
    return project / ".metaos"


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


def _backup(path: Path, meta_home: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = meta_home / "backups"
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


def _inject(path: Path, block: str, meta_home: Path, apply: bool, plans: list[Plan]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    proposed = _replace_marked_block(existing, block)
    if proposed == existing:
        plans.append(Plan("unchanged", path, "managed block already current"))
        return
    plans.append(Plan("inject", path, "replace or append marker-bounded MetaOS block"))
    if not apply:
        return
    _backup(path, meta_home)
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
    meta_home = global_home(home)
    plans: list[Plan] = []
    _write_text(meta_home / "core" / "METAOS-CORE.md", CORE_POLICY, apply, plans)
    for name, skill in SKILLS.items():
        _write_text(meta_home / "skills" / name / "SKILL.md", skill, apply, plans)

    for provider in providers:
        if provider == "codex":
            _inject(home / ".codex" / "AGENTS.md", CODEX_BLOCK, meta_home, apply, plans)
            skill_root = home / ".agents" / "skills"
        else:
            _inject(home / ".claude" / "CLAUDE.md", CLAUDE_BLOCK, meta_home, apply, plans)
            skill_root = home / ".claude" / "skills"
        for name in SKILLS:
            _symlink(meta_home / "skills" / name, skill_root / name, apply, plans)
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
    meta_home = global_home(home)
    local_home = project_home(project)
    plans: list[Plan] = []
    for folder in ("tasks", "staging", "audit", "quarantine"):
        path = local_home / folder
        plans.append(Plan("mkdir", path, "local MetaOS state directory"))
        if apply:
            path.mkdir(parents=True, exist_ok=True)
    _append_git_exclude(project, apply, plans)

    for provider in providers:
        if provider == "codex":
            _inject(project / "AGENTS.md", CODEX_BLOCK, meta_home, apply, plans)
            skill_root = project / ".agents" / "skills"
        else:
            _inject(project / "CLAUDE.local.md", CLAUDE_BLOCK, meta_home, apply, plans)
            skill_root = project / ".claude" / "skills"
        for name in SKILLS:
            _symlink(meta_home / "skills" / name, skill_root / name, apply, plans)
    return plans


def uninstall_global(*, home: Path, providers: Iterable[str], apply: bool) -> list[Plan]:
    meta_home = global_home(home)
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
                    _backup(instruction, meta_home)
                    instruction.write_text(updated, encoding="utf-8")
        for name in SKILLS:
            link = skill_root / name
            if link.is_symlink() and link.resolve() == (meta_home / "skills" / name).resolve():
                plans.append(Plan("unlink", link, "managed skill symlink"))
                if apply:
                    link.unlink()
    return plans


def status(*, project: Path, home: Path) -> dict[str, object]:
    meta_home = global_home(home)
    project = project.resolve()
    return {
        "global_home": str(meta_home),
        "global_core_exists": (meta_home / "core" / "METAOS-CORE.md").exists(),
        "project": str(project),
        "project_metaos_exists": project_home(project).exists(),
        "codex_global_marker": _has_marker(home / ".codex" / "AGENTS.md"),
        "claude_global_marker": _has_marker(home / ".claude" / "CLAUDE.md"),
        "codex_project_marker": _has_marker(project / "AGENTS.md"),
        "claude_project_marker": _has_marker(project / "CLAUDE.local.md"),
    }


def _has_marker(path: Path) -> bool:
    return path.exists() and MARKER_BEGIN in path.read_text(encoding="utf-8")


def create_task(*, project: Path, description: str, risk: str, mode: str, apply: bool = True) -> Path:
    valid_risks = {"R0", "R1", "R2", "R3", "R4"}
    valid_modes = {"observe", "propose", "stage", "commit"}
    if risk not in valid_risks:
        raise ValueError(f"risk must be one of {', '.join(sorted(valid_risks))}")
    if mode not in valid_modes:
        raise ValueError(f"mode must be one of {', '.join(sorted(valid_modes))}")
    task_id = f"task-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    task_dir = project_home(project.resolve()) / "tasks" / task_id
    payload = {
        "schema_version": "1.0",
        "task_id": task_id,
        "description": description,
        "mode": mode,
        "risk": risk,
        "scope": [],
        "exclusions": ["git commit", "git push", "deployment"],
        "success_criteria": [],
        "stop_conditions": ["same approach fails twice without new evidence"],
        "verification_plan": [],
        "rollback_or_containment": ["keep changes staged or reviewable before commit"],
        "status": "active",
        "created_at": datetime.now(UTC).isoformat(),
    }
    if apply:
        task_dir.mkdir(parents=True, exist_ok=False)
        (task_dir / "task-envelope.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return task_dir / "task-envelope.json"


def launch(*, provider: str, project: Path, home: Path, mode: str | None, provider_args: list[str], execute: bool) -> int:
    if provider not in {"codex", "claude"}:
        raise ValueError("provider must be codex or claude")
    task_file = _latest_active_task(project)
    env = os.environ.copy()
    env["METAOS_HOME"] = str(global_home(home))
    env["METAOS_PROJECT_ROOT"] = str(project.resolve())
    if mode:
        env["METAOS_MODE"] = mode
    if task_file:
        env["METAOS_TASK_FILE"] = str(task_file)
    command = [provider, *provider_args]
    if not execute:
        print(json.dumps({"command": command, "env": {k: env[k] for k in env if k.startswith("METAOS_")}}, ensure_ascii=False, indent=2))
        return 0
    try:
        return subprocess.run(command, cwd=project, env=env, check=False).returncode
    except FileNotFoundError:
        print(f"Provider command not found: {provider}", file=sys.stderr)
        return 127


def _latest_active_task(project: Path) -> Path | None:
    tasks = project_home(project.resolve()) / "tasks"
    if not tasks.exists():
        return None
    candidates = sorted(tasks.glob("*/task-envelope.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None
