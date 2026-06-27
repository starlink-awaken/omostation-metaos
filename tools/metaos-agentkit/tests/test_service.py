from __future__ import annotations

import json
from pathlib import Path

from metaos_agentkit.service import create_task, install_global, install_local, status, uninstall_global


def test_global_init_preserves_existing_content_and_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    existing = home / ".codex" / "AGENTS.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# Existing rules\n", encoding="utf-8")

    install_global(home=home, providers=("codex",), apply=True)
    first = existing.read_text(encoding="utf-8")
    assert "# Existing rules" in first
    assert "METAOS-AGENTKIT:BEGIN" in first
    assert (home / ".metaos" / "agentkit" / "core" / "METAOS-CORE.md").is_file()
    assert (home / ".agents" / "skills" / "metaos-repo-change").is_symlink()

    install_global(home=home, providers=("codex",), apply=True)
    assert existing.read_text(encoding="utf-8") == first


def test_local_init_keeps_metaos_out_of_shared_gitignore(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".git" / "info").mkdir(parents=True)
    install_global(home=home, providers=("codex", "claude"), apply=True)
    install_local(project=project, home=home, providers=("codex", "claude"), apply=True)

    assert (project / ".metaos" / "agentkit" / "tasks").is_dir()
    assert ".metaos/" in (project / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert not (project / ".gitignore").exists()
    assert "METAOS-AGENTKIT:BEGIN" in (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "METAOS-AGENTKIT:BEGIN" in (project / "CLAUDE.local.md").read_text(encoding="utf-8")


def test_task_projection_matches_canonical_agent_session_shape(tmp_path: Path) -> None:
    task = create_task(project=tmp_path, description="Fix bug", risk="R2", mode="stage")
    payload = json.loads(task.read_text(encoding="utf-8"))
    assert task.name == "agent-session.json"
    assert ".metaos/agentkit/tasks" in task.as_posix()
    assert payload["description"] == "Fix bug"
    assert payload["risk"] == "R2"
    assert payload["mode"] == "stage"
    assert payload["status"] == "prepared"
    assert payload["decision_id"] == ""
    assert payload["asset_id"] == ""


def test_uninstall_only_removes_managed_block_and_link(tmp_path: Path) -> None:
    home = tmp_path / "home"
    target = home / ".codex" / "AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Keep me\n", encoding="utf-8")
    install_global(home=home, providers=("codex",), apply=True)
    uninstall_global(home=home, providers=("codex",), apply=True)

    assert target.read_text(encoding="utf-8").strip() == "# Keep me"
    assert not (home / ".agents" / "skills" / "metaos-repo-change").exists()


def test_status_reports_owned_state_without_claiming_core_ownership(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    install_global(home=home, providers=("codex",), apply=True)
    install_local(project=project, home=home, providers=("codex",), apply=True)
    result = status(project=project, home=home)
    assert result["global_core_exists"] is True
    assert result["agentkit_project_exists"] is True
    assert result["codex_global_marker"] is True
    assert result["metaos_root"] == str(home / ".metaos")


def test_launch_preview_does_not_gate_or_forward_adapter_options(tmp_path: Path, capsys) -> None:
    from metaos_agentkit.cli import main

    project = tmp_path / "project"
    project.mkdir()
    create_task(project=project, description="Preview stage", risk="R2", mode="stage")
    assert main(["--home", str(tmp_path / "home"), "launch", "codex", "--mode", "stage", "--path", str(project), "--", "--help"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider_command"] == ["codex", "--help"]
    assert "prepare" in payload["bridge_command"]
    assert payload["note"].startswith("Preview only")
