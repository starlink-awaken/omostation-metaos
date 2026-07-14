"""ADR-0181 Phase 4 hardening tests: data pack, bus adapter, session integrity, profiles."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ── 4a cognitive pack ──────────────────────────────────────────────


def test_bundled_manifest_and_frameworks_exist():
    root = Path(__file__).resolve().parents[1] / "src" / "metaos" / "resources" / "cognitive_framework"
    assert (root / "MANIFEST.json").is_file()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] >= 1
    assert any(root.glob("*.yaml"))


def test_prefer_bundled(monkeypatch):
    monkeypatch.setenv("METAOS_PREFER_BUNDLED", "1")
    monkeypatch.delenv("METAOS_COGNITIVE_FRAMEWORK_DIR", raising=False)
    from metaos.core.cognitive_framework import CognitiveFrameworkLoader, resolve_cognitive_framework_dir

    d = resolve_cognitive_framework_dir()
    assert d is not None
    assert "resources" in str(d) or (d / "MANIFEST.json").exists() or any(d.glob("*.yaml"))
    loader = CognitiveFrameworkLoader()
    assert isinstance(loader.frameworks, list)


def test_sync_check_script():
    from pathlib import Path
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "sync_cognitive_frameworks.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--check"],
        capture_output=True,
        text=True,
        cwd=str(script.parent.parent),
    )
    # monorepo: should be in sync after Phase 4 sync
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── 4b bus adapter ─────────────────────────────────────────────────


def test_event_bus_mode_off(monkeypatch):
    monkeypatch.setenv("METAOS_EVENT_BUS", "off")
    from metaos.integrations.bus_adapter import event_bus_mode, publish_node_event

    assert event_bus_mode() == "off"
    r = publish_node_event("wf", "n1", "completed")
    assert r["mode"] == "off"
    assert r["bus"] is False
    assert r["http"] is False


def test_publish_http_mode_mocked(monkeypatch):
    monkeypatch.setenv("METAOS_EVENT_BUS", "http")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        class R:
            status_code = 200

        return R()

    import metaos.integrations.bus_adapter as ba

    monkeypatch.setattr(ba.requests, "post", fake_post)
    r = ba.publish_node_event("wf", "n1", "failed", task_type="reasoning")
    assert r["http"] is True
    assert calls


# ── 4c integrity ───────────────────────────────────────────────────


def test_integrity_sign_verify_roundtrip(monkeypatch):
    monkeypatch.setenv("METAOS_SESSION_INTEGRITY_SECRET", "test-secret-phase4")
    monkeypatch.setenv("METAOS_SESSION_INTEGRITY_REQUIRED", "1")
    from metaos.integrations.agent_runtime.integrity import (
        attach_integrity,
        verify_session_dict,
    )

    data = {"session_id": "agent-abc", "status": "prepared", "asset_id": "session-agent-abc"}
    signed = attach_integrity(data)
    assert signed.get("integrity_hmac")
    ok, reason = verify_session_dict(signed)
    assert ok, reason
    # tamper
    signed["status"] = "finalized"
    ok2, reason2 = verify_session_dict(signed)
    assert not ok2
    assert "mismatch" in reason2


def test_canonical_load_rejects_tamper(tmp_path, monkeypatch):
    monkeypatch.setenv("METAOS_SESSION_INTEGRITY_SECRET", "sec")
    monkeypatch.setenv("METAOS_SESSION_INTEGRITY_REQUIRED", "1")
    from metaos.core.engine import SEngine
    from metaos.integrations.agent_runtime.canonical import load_canonical_session
    from metaos.integrations.agent_runtime.contracts import AgentSession
    from metaos.integrations.agent_runtime.integrity import attach_integrity
    from metaos.integrations.agent_runtime.service import AgentRuntimeService

    eng = SEngine(data_dir=str(tmp_path / "data"))
    token = eng.register_h("h1", "H")
    eng.authenticate(token)
    svc = AgentRuntimeService(eng)
    session = AgentSession(h_id=eng._current_h_id, description="test integrity")
    svc._persist_session_asset(session, "owner")
    # tamper asset on disk
    asset_path = Path(eng.d.assets_dir) / f"{session.asset_id}.json"
    stored = json.loads(asset_path.read_text(encoding="utf-8"))
    content = json.loads(stored["content"])
    content["description"] = "TAMPERED"
    stored["content"] = json.dumps(content)
    asset_path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        load_canonical_session(eng, session)


# ── 4c capability profile overlay ──────────────────────────────────


def test_capability_profile_overlay(tmp_path, monkeypatch):
    policy = tmp_path / "profiles.yaml"
    policy.write_text(
        """
profiles:
  custom-read:
    allowed_risks: [R0, R1]
    allowed_modes: [observe, propose]
    codex_sandbox: read-only
    codex_approval: on-request
    network: false
    isolate_git_worktree: false
    allow_explicit_mcp: false
    require_human_confirmation_for_launch: false
    description: custom
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("METAOS_CAPABILITY_PROFILES", str(policy))
    import metaos.integrations.agent_runtime.capabilities as cap

    # force reload
    cap._profiles_overlay_loaded = False
    cap.load_profile_overlays(force=True)
    assert "custom-read" in cap.PROFILES
    assert cap.PROFILES["custom-read"].description == "custom"
