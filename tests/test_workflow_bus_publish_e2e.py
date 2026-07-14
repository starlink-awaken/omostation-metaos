"""E2E: metaos.workflow publishes metaos:node:* events to bus-foundation.

Round 2 verification: _publish_event must (a) emit on bus-foundation
when available, (b) fall back to HTTP POST when bus-foundation is
unavailable, (c) never raise.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from unittest.mock import patch

import pytest


def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeNode:
    def __init__(self, status: str = "completed", node_id: str = "n1", task_type: str = "search") -> None:
        self.status = status
        self.node_id = node_id
        self.task_type = task_type


class _FakeWorkflow:
    """Minimal Workflow stand-in that just exposes _publish_event."""

    def __init__(self, workflow_id: str = "wf-test") -> None:
        self.workflow_id = workflow_id

    # Import the real methods via copy
    from metaos.core.workflow import Workflow  # type: ignore[attr-defined]


def test_publish_event_uses_bus_foundation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When bus-foundation is available, _publish_event must emit on the bus."""
    from bus_foundation.backends.eventbus import EventBusBackend
    from bus_foundation import _backends

    be = EventBusBackend()
    received: list = []
    be.subscribe("metaos:*", lambda env: received.append(env))
    monkeypatch.setitem(_backends, "eventbus", be)

    # Patch requests.post to detect any HTTP fallback (should NOT be called)
    with patch("metaos.core.workflow.requests.post") as http_post:
        from metaos.core.workflow import Workflow

        wf = Workflow.__new__(Workflow)  # bypass __init__
        wf.workflow_id = "wf-test"
        wf._publish_event(_FakeNode(status="completed", node_id="n1"))

        assert _wait_for(lambda: len(received) >= 1)
        env = received[0]
        assert env.topic == "metaos:node:completed"
        assert env.payload["workflow_id"] == "wf-test"
        assert env.payload["node_id"] == "n1"
        # No HTTP fallback should have been called
        assert not http_post.called, f"HTTP fallback called: {http_post.call_args}"


def test_publish_human_approval_uses_bus_foundation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Human approval publishes metaos:node:awaiting_approval on the bus."""
    from bus_foundation.backends.eventbus import EventBusBackend
    from bus_foundation import _backends

    be = EventBusBackend()
    received: list = []
    be.subscribe("metaos:*", lambda env: received.append(env))
    monkeypatch.setitem(_backends, "eventbus", be)

    with patch("metaos.core.workflow.requests.post") as http_post:
        from metaos.core.workflow import Workflow

        wf = Workflow.__new__(Workflow)
        wf.workflow_id = "wf-approval"
        node = _FakeNode(status="awaiting_approval", node_id="n2")
        node.output = "needs review"
        wf._publish_human_approval_event(node)

        assert _wait_for(lambda: len(received) >= 1)
        env = received[0]
        assert env.topic == "metaos:node:awaiting_approval"
        assert env.payload["reason"] == "needs review"
        assert not http_post.called


def test_legacy_env_flag_forces_http_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """METAOS_LEGACY_AGORA_HTTP=1 must force HTTP path even if bus is up."""
    from bus_foundation.backends.eventbus import EventBusBackend
    from bus_foundation import _backends

    be = EventBusBackend()
    received: list = []
    be.subscribe("metaos:*", lambda env: received.append(env))
    monkeypatch.setitem(_backends, "eventbus", be)
    monkeypatch.setenv("METAOS_LEGACY_AGORA_HTTP", "1")

    with patch("metaos.core.workflow.requests.post") as http_post:
        http_post.return_value.status_code = 200
        from metaos.core.workflow import Workflow

        wf = Workflow.__new__(Workflow)
        wf.workflow_id = "wf-legacy"
        wf._publish_event(_FakeNode(status="completed", node_id="n3"))

        # Bus should NOT have been called
        assert not _wait_for(lambda: len(received) >= 1, timeout=0.2)
        # HTTP fallback should have been called
        assert http_post.called


def test_publish_event_survives_bus_foundation_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When bus-foundation is NOT installed, _publish_event falls back to HTTP."""
    # Simulate missing bus-foundation by injecting ImportError
    import sys

    # Hide bus_foundation.facade
    saved = sys.modules.pop("bus_foundation.facade", None)
    sys.modules["bus_foundation.facade"] = None  # type: ignore[assignment]
    try:
        with patch("metaos.core.workflow.requests.post") as http_post:
            http_post.return_value.status_code = 200
            from metaos.core.workflow import Workflow

            wf = Workflow.__new__(Workflow)
            wf.workflow_id = "wf-nobus"
            wf._publish_event(_FakeNode(status="failed", node_id="n4"))
            assert http_post.called
    finally:
        if saved is not None:
            sys.modules["bus_foundation.facade"] = saved


def test_publish_event_survives_publish_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If bus_publish() raises, _publish_event must swallow + try HTTP fallback."""
    from bus_foundation.facade import event as facade_event

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated")

    monkeypatch.setattr(facade_event, "publish", _boom)
    with patch("metaos.core.workflow.requests.post") as http_post:
        http_post.return_value.status_code = 200
        from metaos.core.workflow import Workflow

        wf = Workflow.__new__(Workflow)
        wf.workflow_id = "wf-boom"
        wf._publish_event(_FakeNode(status="running", node_id="n5"))
        # Bus raised → HTTP fallback ran
        assert http_post.called
