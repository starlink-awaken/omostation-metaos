"""Provider version smoke tests (Phase D)."""

from __future__ import annotations

import os
from pathlib import Path

from metaos.integrations.agent_runtime.provider_versions import (
    _extract_version,
    probe_all,
    smoke_report,
)


def test_extract_version():
    assert _extract_version("codex-cli 0.42.1") == "0.42.1"
    assert _extract_version("1.2") == "1.2"
    assert _extract_version("nope") is None


def test_smoke_report_shape():
    report = smoke_report()
    assert "providers" in report
    assert isinstance(report["providers"], list)
    assert len(report["providers"]) >= 2
    for p in report["providers"]:
        assert "name" in p
        assert "available" in p


def test_probe_with_stub_path(tmp_path, monkeypatch):
    stub = tmp_path / "codex"
    stub.write_text("#!/bin/sh\necho 'codex 9.9.9'\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH','')}")
    from metaos.integrations.agent_runtime import provider_versions as pv

    r = pv.probe_codex()
    assert r.available
    assert r.version == "9.9.9"


def test_probe_all_returns_two():
    rows = probe_all()
    names = {r.name for r in rows}
    assert "codex" in names
    assert "claude" in names
