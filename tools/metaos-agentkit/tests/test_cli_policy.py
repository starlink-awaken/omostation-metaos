from __future__ import annotations

import pytest

from metaos_agentkit.cli import _inferred_profile
from metaos_agentkit.service import _validate_provider_args


@pytest.mark.parametrize(
    ("provider", "args"),
    [
        ("codex", ["--sandbox", "danger-full-access"]),
        ("codex", ["--full-auto"]),
        ("codex", ["--search"]),
        ("claude", ["--settings", "other.json"]),
        ("claude", ["--mcp-config", "other.json"]),
    ],
)
def test_provider_flags_cannot_replace_capability_boundary(provider: str, args: list[str]) -> None:
    with pytest.raises(ValueError, match="capability boundary"):
        _validate_provider_args(provider, args)


def test_cli_infers_high_risk_stage_profile_without_upgrading_to_commit() -> None:
    assert _inferred_profile("R4", "stage", None) == "high-risk-stage"
    assert _inferred_profile("R4", "commit", None) is None
    assert _inferred_profile("R4", "stage", "repo-stage") == "repo-stage"
