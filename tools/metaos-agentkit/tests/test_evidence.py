from __future__ import annotations

import json
from pathlib import Path

from metaos_agentkit.evidence import capture_finalization_evidence


def test_finalization_evidence_records_audit_hashes_and_provider_exit(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    audit = task_dir / "audit"
    audit.mkdir(parents=True)
    (audit / "launch-plan.json").write_text(
        json.dumps({"provider": "codex", "worktree_path": None, "command": ["codex"]}),
        encoding="utf-8",
    )
    (audit / "provider-exit.json").write_text(
        json.dumps({"returncode": 0, "finalization_required": True}),
        encoding="utf-8",
    )

    path = capture_finalization_evidence(task_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["audit_files"]["launch_plan"]["sha256"]
    assert payload["audit_files"]["provider_exit"]["sha256"]
    assert payload["worktree"]["available"] is False
    assert payload["audit_files"]["provider_exit"]["available"] is True
