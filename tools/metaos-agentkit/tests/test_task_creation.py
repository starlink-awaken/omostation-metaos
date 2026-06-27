from __future__ import annotations

import json
from pathlib import Path

import pytest

from metaos_agentkit.task_creation import create_task


def test_high_risk_commit_requires_target_binding(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="require an explicit target binding"):
        create_task(
            project=tmp_path,
            description="Create external event",
            risk="R3",
            mode="commit",
        )


def test_high_risk_commit_projection_contains_binding_and_verification_plan(tmp_path: Path) -> None:
    path = create_task(
        project=tmp_path,
        description="Create a calendar event",
        risk="R3",
        mode="commit",
        target_kind="calendar_event",
        target="calendar:primary",
        operation="create_event",
        scope=["recipient:alice@example.com", "duration:30m"],
        expires_in_minutes=30,
        success_criteria=["Calendar event id is returned"],
        verification_commands=["calendar.get_event <id>"],
        verification_expected_outcomes=["event exists with Alice as attendee"],
        rollback_or_containment=["delete the newly created event"],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["target_binding"]["kind"] == "calendar_event"
    assert payload["target_binding"]["target"] == "calendar:primary"
    assert payload["target_binding"]["scope"] == ["recipient:alice@example.com", "duration:30m"]
    assert payload["success_criteria"] == ["Calendar event id is returned"]
    assert payload["verification"]["expected_outcomes"] == ["event exists with Alice as attendee"]
    assert payload["rollback_or_containment"] == ["delete the newly created event"]


def test_partial_target_binding_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Target binding requires"):
        create_task(
            project=tmp_path,
            description="Create external event",
            risk="R3",
            mode="commit",
            target_kind="calendar_event",
            target="calendar:primary",
        )
