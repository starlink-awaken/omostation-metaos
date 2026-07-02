"""Tests for metaos cognitive framework (morning/evening/review).

Covers PARTIAL capability: morning/evening/review were not directly
tested, only indirectly via evidence tests.
"""

from unittest import mock

import pytest

from metaos.cli import CLI
from metaos.core.engine import SEngine
from metaos.core.types import Task, TaskType


@pytest.fixture
def engine(tmp_path):
    """Create a test SEngine with mock backend."""
    eng = SEngine(data_dir=str(tmp_path / "metaos_data"))
    token = eng.register_h("test_h", "Test User")
    eng.authenticate(token)
    return eng


@pytest.fixture
def cli(engine):
    """Create CLI bound to test engine."""
    return CLI(engine)


class TestMorningRitual:
    """Morning ritual (晨间仪式) tests."""

    def test_morning_returns_result(self, cli):
        """morning() returns a result dict with output."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "Morning focus set", "status": "ok"}
            result = cli.morning("今日焦点")
        assert "output" in result
        assert result["status"] == "ok"

    def test_morning_uses_morning_ritual_type(self, cli):
        """morning() creates a Task with MORNING_RITUAL type."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "", "status": "ok"}
            cli.morning("test")
        call_args = mock_proc.call_args
        task = call_args[0][0]
        assert task.task_type == TaskType.MORNING_RITUAL.value

    def test_morning_default_note(self, cli):
        """morning() with no note uses default text."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "", "status": "ok"}
            cli.morning()
        task = mock_proc.call_args[0][0]
        assert task.input  # non-empty default


class TestEveningReview:
    """Evening integration (晚间整合) tests."""

    def test_evening_returns_result(self, cli):
        """evening() returns a result dict with output."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "Evening synthesis", "status": "ok"}
            result = cli.evening("今日收获")
        assert "output" in result

    def test_evening_uses_evening_review_type(self, cli):
        """evening() creates a Task with EVENING_REVIEW type."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "", "status": "ok"}
            cli.evening("test")
        task = mock_proc.call_args[0][0]
        assert task.task_type == TaskType.EVENING_REVIEW.value


class TestMicroReview:
    """Micro-review (微粒复盘) tests."""

    def test_review_returns_result(self, cli):
        """review() returns a result dict."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "Review complete", "status": "ok"}
            result = cli.review("action", "expected", "actual")
        assert "output" in result

    def test_review_passes_action_expected_actual(self, cli):
        """review() includes action, expected, and actual in the task input."""
        with mock.patch.object(cli.engine, "process") as mock_proc:
            mock_proc.return_value = {"output": "", "status": "ok"}
            cli.review("did X", "expected Y", "got Z")
        task = mock_proc.call_args[0][0]
        assert "did X" in task.input
        assert "expected Y" in task.input
        assert "got Z" in task.input
