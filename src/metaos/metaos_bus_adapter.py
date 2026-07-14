"""Backward-compatible shim → metaos.integrations.bus_adapter (ADR-0181 Phase 4b)."""

from __future__ import annotations

from metaos.integrations.bus_adapter import (
    event_bus_mode,
    publish_human_approval_event,
    publish_node_event,
    publish_via_bus,
    publish_via_http,
)

__all__ = [
    "event_bus_mode",
    "publish_node_event",
    "publish_human_approval_event",
    "publish_via_bus",
    "publish_via_http",
]
