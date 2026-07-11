"""metaos bus adapter — bridges metaos events to agora.bus facade.

Phase A.1: metaos.workflow still uses raw `requests.post` to localhost
for tight coupling (sub-2s timeout, Bearer token). This adapter adds
bus-facade publishing for *new* metaos consumers, without modifying
the legacy workflow internals.

NOTE: metaos ↔ agora circular dep not yet resolved (R58+ work).
For now, this adapter is demo-only and does NOT integrate with workflow.py.
"""
from __future__ import annotations

import uuid
from typing import Any

from bus_foundation.facade import event as bus_event


def _get_trace_id() -> str | None:
    """Try to inherit trace_id from bus-foundation R94 context."""
    try:
        from bus_foundation.observability import get_current_trace_id
        return get_current_trace_id()
    except ImportError:
        return None


def publish_node_event(
    workflow_id: str,
    node_id: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> str:
    trace_id = _get_trace_id() or f"metaos-{uuid.uuid4().hex[:6]}"
    topic = f"node_{status}"
    bus_event.publish(
        topic=topic,
        payload={
            "workflow_id": workflow_id,
            "node_id": node_id,
            "status": status,
            **(payload or {}),
        },
        source_uri="bos://governance/metaos_workflow",
        trace_id=trace_id,
    )
    return trace_id
