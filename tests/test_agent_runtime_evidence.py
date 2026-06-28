from __future__ import annotations

import json
from pathlib import Path

import pytest

from metaos.agent_cli import MAX_EVIDENCE_BUNDLE_BYTES, _read_evidence_bundle


def test_read_evidence_bundle_hashes_structured_payload(tmp_path: Path) -> None:
    source = tmp_path / "evidence.json"
    source.write_text(json.dumps({"schema_version": "1.0", "provider_exit": {"returncode": 0}}), encoding="utf-8")

    bundle = _read_evidence_bundle(source)

    assert bundle["sha256"]
    assert bundle["payload"]["provider_exit"]["returncode"] == 0


def test_read_evidence_bundle_rejects_oversized_payload(tmp_path: Path) -> None:
    source = tmp_path / "large.json"
    source.write_bytes(b"{" + (b"x" * MAX_EVIDENCE_BUNDLE_BYTES) + b"}")

    with pytest.raises(ValueError, match="size limit"):
        _read_evidence_bundle(source)
