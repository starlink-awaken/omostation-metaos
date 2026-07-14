#!/usr/bin/env python3
"""Sync ecos MOF CognitiveFramework YAML → metaos bundled resources (ADR-0181 Phase 4a).

SSOT remains projects/ecos/.../m1/cognitive_framework.
metaos/resources/cognitive_framework is a distributable mirror for offline load.

Usage (from metaos project root):
  uv run python scripts/sync_cognitive_frameworks.py
  uv run python scripts/sync_cognitive_frameworks.py --check   # fail if drift
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

METAOS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = METAOS_ROOT / "src" / "metaos" / "resources" / "cognitive_framework"
# monorepo: projects/metaos → projects/ecos
DEFAULT_SRC = METAOS_ROOT.parent / "ecos" / "src" / "ecos" / "ssot" / "mof" / "m1" / "cognitive_framework"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def resolve_src(cli: str | None) -> Path:
    if cli:
        return Path(cli).expanduser().resolve()
    import os

    env = os.environ.get("ECOS_COGNITIVE_FRAMEWORK_DIR") or os.environ.get(
        "METAOS_COGNITIVE_FRAMEWORK_DIR", ""
    )
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SRC.resolve()


def sync(src: Path, dst: Path) -> dict:
    if not src.is_dir():
        raise FileNotFoundError(f"source cognitive_framework dir missing: {src}")
    dst.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for path in sorted(src.glob("*.yaml")):
        target = dst / path.name
        shutil.copy2(path, target)
        files[path.name] = _sha256_file(target)
    # remove stale yaml not in source
    for path in dst.glob("*.yaml"):
        if path.name not in files:
            path.unlink()
    manifest = {
        "version": 1,
        "source": str(src),
        "synced_at": datetime.now(UTC).isoformat(),
        "file_count": len(files),
        "files": files,
        "ssot": "ecos/ssot/mof/m1/cognitive_framework",
        "adr": "ADR-0181",
    }
    (dst / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def check_drift(src: Path, dst: Path) -> list[str]:
    """Return list of drift messages (empty = in sync)."""
    issues: list[str] = []
    if not src.is_dir():
        return [f"source missing: {src}"]
    manifest_path = dst / "MANIFEST.json"
    if not manifest_path.exists():
        return ["MANIFEST.json missing — run sync"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["MANIFEST.json invalid"]
    src_files = {p.name: _sha256_file(p) for p in src.glob("*.yaml")}
    recorded = manifest.get("files") or {}
    if set(src_files) != set(recorded):
        issues.append(f"file set drift src={sorted(src_files)} bundled={sorted(recorded)}")
    for name, digest in src_files.items():
        if recorded.get(name) != digest:
            issues.append(f"hash drift: {name}")
        bundled = dst / name
        if not bundled.exists():
            issues.append(f"missing bundled: {name}")
        elif _sha256_file(bundled) != digest:
            issues.append(f"content drift: {name}")
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sync MOF cognitive frameworks into metaos")
    ap.add_argument("--src", default=None, help="source dir (ecos MOF cognitive_framework)")
    ap.add_argument("--dst", default=str(DEFAULT_DST), help="destination resources dir")
    ap.add_argument("--check", action="store_true", help="check drift only (exit 1 if drift)")
    args = ap.parse_args(argv)
    src = resolve_src(args.src)
    dst = Path(args.dst).expanduser().resolve()
    if args.check:
        issues = check_drift(src, dst)
        if issues:
            print("cognitive-framework drift:")
            for i in issues:
                print(f"  - {i}")
            return 1
        print("cognitive-framework: OK (in sync with SSOT)")
        return 0
    manifest = sync(src, dst)
    print(f"synced {manifest['file_count']} frameworks → {dst}")
    print(f"manifest: {dst / 'MANIFEST.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
