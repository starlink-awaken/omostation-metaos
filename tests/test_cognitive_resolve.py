"""Cognitive framework path resolution (ADR-0181 Phase 1c)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from metaos.core.cognitive_framework import (
    CognitiveFrameworkLoader,
    resolve_cognitive_framework_dir,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for key in (
        "METAOS_COGNITIVE_FRAMEWORK_DIR",
        "ECOS_MOF_M1_DIR",
        "ECOS_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_resolve_uses_env_dir(tmp_path, monkeypatch):
    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "custom.yaml").write_text(
        "type: CognitiveFramework\nname: Custom\nproperties:\n  trigger_conditions: [架构]\n  personas: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("METAOS_COGNITIVE_FRAMEWORK_DIR", str(fw))
    assert resolve_cognitive_framework_dir() == fw.resolve()

    loader = CognitiveFrameworkLoader()
    assert len(loader.frameworks) >= 1
    prompt = loader.build_cognitive_prompt("架构评审")
    assert "Custom" in prompt or "框架" in prompt


def test_resolve_falls_back_to_bundled_or_monorepo():
    """Without env, should still find monorepo MOF or bundled resources."""
    d = resolve_cognitive_framework_dir()
    assert d is not None
    assert d.is_dir()
    assert any(d.glob("*.yaml"))


def test_loader_accepts_type_field_not_only_m1_type(tmp_path):
    """YAML uses type: CognitiveFramework (not m1_type)."""
    (tmp_path / "a.yaml").write_text(
        "type: CognitiveFramework\nname: A\nproperties:\n"
        "  framework_name: FrameA\n  trigger_conditions: [决策]\n"
        "  personas:\n    - role: R\n      focus: F\n",
        encoding="utf-8",
    )
    loader = CognitiveFrameworkLoader(m1_dir=tmp_path)
    assert len(loader.frameworks) == 1
    assert "FrameA" in loader.build_cognitive_prompt("需要决策")


def test_no_fixed_parents4_hardcode():
    import inspect

    from metaos.core import cognitive_framework as mod

    src = inspect.getsource(mod)
    assert "parents[4]" not in src
