"""Tests for metaos day ritual (onboard 7-day guide).

Covers the MISSING capability: metaos day <1-7> had zero test coverage.
Tests the non-interactive logic: state management, recovery path, and
day-step structure without requiring user input.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from metaos.onboard import (
    _detect_interrupt,
    _load_state,
    _recover_path,
    _save_state,
)


class TestStateManagement:
    """Onboard state load/save round-trip."""

    def test_load_state_default(self, tmp_path):
        """No existing state returns default dict."""
        with mock.patch("metaos.onboard.ONBOARD_FILE", tmp_path / "onboard.json"):
            state = _load_state()
        assert state == {"day": 0, "last_active": None, "completed": False}

    def test_save_then_load(self, tmp_path):
        """Save state and load it back."""
        f = tmp_path / "onboard.json"
        with mock.patch("metaos.onboard.ONBOARD_FILE", f):
            _save_state({"day": 3, "last_active": "2026-07-01T10:00:00", "completed": False})
            state = _load_state()
        assert state["day"] == 3
        assert state["completed"] is False

    def test_load_state_corrupt_file(self, tmp_path):
        """Corrupt JSON falls back to default."""
        f = tmp_path / "onboard.json"
        f.write_text("NOT JSON {{{")
        with mock.patch("metaos.onboard.ONBOARD_FILE", f):
            state = _load_state()
        assert state["day"] == 0


class TestRecoveryPath:
    """Interrupt detection and recovery day calculation."""

    def test_recover_no_interrupt(self):
        """0-2 days gone: no rollback."""
        assert _recover_path(0) == 0
        assert _recover_path(1) == 0
        assert _recover_path(2) == 0

    def test_recover_moderate_interrupt(self):
        """3-5 days gone: rollback 3 days."""
        assert _recover_path(3) == -3
        assert _recover_path(5) == -3

    def test_recover_long_interrupt(self):
        """6+ days gone: restart from beginning."""
        assert _recover_path(6) == -99
        assert _recover_path(30) == -99

    def test_detect_interrupt_no_last_active(self):
        """No last_active returns 0."""
        state = {"last_active": None}
        assert _detect_interrupt(state) == 0

    def test_detect_interrupt_with_last_active(self):
        """Computes elapsed days from last_active."""
        from datetime import datetime, timedelta

        state = {"last_active": (datetime.now() - timedelta(days=3)).isoformat()}
        elapsed = _detect_interrupt(state)
        assert elapsed >= 3


class TestDayStructure:
    """Verify each day 1-7 has defined steps in the onboard guide."""

    def test_all_7_days_defined(self):
        """The onboard run() function handles days 1 through 7."""
        import metaos.onboard as onboard
        import inspect

        source = inspect.getsource(onboard.run)
        for day in range(1, 8):
            assert f"day == {day}" in source, f"Day {day} not found in onboard.run()"

    def test_day1_has_morning_and_evening(self):
        """Day 1 includes both morning ritual and evening integration."""
        import metaos.onboard as onboard
        import inspect

        source = inspect.getsource(onboard.run)
        # Find day 1 block
        day1_start = source.index("day == 1")
        day2_start = source.index("day == 2")
        day1_block = source[day1_start:day2_start]
        assert "morning" in day1_block
        assert "evening" in day1_block

    def test_day7_has_closing_ritual(self):
        """Day 7 includes the closing ceremony."""
        import metaos.onboard as onboard
        import inspect

        source = inspect.getsource(onboard.run)
        day7_start = source.index("day == 7")
        day7_block = source[day7_start:]
        assert "evening" in day7_block
        assert "启动完成" in day7_block or "闭环" in day7_block

    def test_day2_has_review(self):
        """Day 2 includes micro-review (cli.review)."""
        import metaos.onboard as onboard
        import inspect

        source = inspect.getsource(onboard.run)
        day2_start = source.index("day == 2")
        day3_start = source.index("day == 3")
        day2_block = source[day2_start:day3_start]
        assert "review" in day2_block

    def test_day3_has_gate(self):
        """Day 3 includes decision gate (cli.gate)."""
        import metaos.onboard as onboard
        import inspect

        source = inspect.getsource(onboard.run)
        day3_start = source.index("day == 3")
        day4_start = source.index("day == 4")
        day3_block = source[day3_start:day4_start]
        assert "gate" in day3_block
