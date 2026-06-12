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

from agora.bus import BusEnvelope
from agora.bus import publish as bus_publish


def publish_node_event(
    workflow_id: str,
    node_id: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> str:
    """Publish a workflow node status event via bus facade.

    Returns event_id.
    """
    env = BusEnvelope(
        type=f"node_{status}",  # matches workflow.py:261 event_type format
        source="metaos_workflow",
        payload={
            "workflow_id": workflow_id,
            "node_id": node_id,
            "status": status,
            **(payload or {}),
        },
        trace_id=f"metaos-{uuid.uuid4().hex[:6]}",
    )
    return bus_publish(env)
