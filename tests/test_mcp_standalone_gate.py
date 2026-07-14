"""Standalone MCP entry gate (ADR-0181 Phase 2)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def test_mcp_exits_without_allow_flag():
    env = os.environ.copy()
    env["METAOS_MCP_ALLOW_STANDALONE"] = "0"
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "metaos.mcp_server"],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        cwd=str(ROOT),
    )
    assert proc.returncode == 2, proc.stderr
    combined = (proc.stderr or "") + (proc.stdout or "")
    assert "Standalone MCP disabled" in combined or "ADR-0181" in combined
