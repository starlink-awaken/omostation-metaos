"""Provider version smoke probes (Agent Runtime Phase D remainder / ADR-0181).

Detects locally installed Codex / Claude Code (or claude) CLI versions without
requiring network. Used by doctor-style checks and unit tests with PATH stubs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderVersionReport:
    name: str
    command: str | None
    available: bool
    version: str | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _run_version(argv: list[str], timeout: float = 3.0) -> tuple[bool, str, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except FileNotFoundError:
        return False, "", "not_found"
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:  # noqa: BLE001
        return False, "", f"error:{e}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0 or bool(out.strip()), out.strip(), f"exit={proc.returncode}"


def _extract_version(text: str) -> str | None:
    m = _VERSION_RE.search(text)
    return m.group(1) if m else None


def probe_codex() -> ProviderVersionReport:
    cmd = shutil.which("codex")
    if not cmd:
        return ProviderVersionReport("codex", None, False, None, "missing_on_path")
    ok, text, detail = _run_version([cmd, "--version"])
    if not ok and not text:
        ok, text, detail = _run_version([cmd, "version"])
    ver = _extract_version(text) if text else None
    return ProviderVersionReport("codex", cmd, bool(ver or ok), ver, detail if not ver else "ok")


def probe_claude() -> ProviderVersionReport:
    # Claude Code CLI is commonly `claude`
    cmd = shutil.which("claude") or shutil.which("claude-code")
    if not cmd:
        return ProviderVersionReport("claude", None, False, None, "missing_on_path")
    ok, text, detail = _run_version([cmd, "--version"])
    ver = _extract_version(text) if text else None
    return ProviderVersionReport("claude", cmd, bool(ver or ok), ver, detail if not ver else "ok")


def probe_all() -> list[ProviderVersionReport]:
    return [probe_codex(), probe_claude()]


def smoke_report() -> dict[str, Any]:
    reports = probe_all()
    return {
        "providers": [r.to_dict() for r in reports],
        "any_available": any(r.available for r in reports),
        "all_available": all(r.available for r in reports),
    }
