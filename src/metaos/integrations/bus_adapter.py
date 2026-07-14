"""Production bus adapter for metaos events (ADR-0181 Phase 4b).

Publish path (controlled by METAOS_EVENT_BUS):
  bus   — bus_foundation facade only
  http  — legacy Agora HTTP SSE only (default when bus unavailable)
  both  — try bus first, then HTTP (default when bus importable)
  off   — no-op

Does not hard-require bus_foundation at import time (soft dependency).
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import requests

logger = logging.getLogger("metaos.bus_adapter")

_AGORA_API_URL = os.environ.get("AGORA_API_URL", "http://127.0.0.1:8080")
_AGORA_TOKEN = os.environ.get("METAOS_AGORA_EVENT_TOKEN", "omo_core_token")


def event_bus_mode() -> str:
    mode = os.environ.get("METAOS_EVENT_BUS", "").strip().lower()
    if mode in {"bus", "http", "both", "off"}:
        return mode
    # auto: both if bus_foundation present else http
    try:
        import bus_foundation  # noqa: F401

        return "both"
    except ImportError:
        return "http"


def _get_trace_id() -> str | None:
    try:
        from bus_foundation.observability import get_current_trace_id

        return get_current_trace_id()
    except Exception:
        return None


def publish_via_bus(
    topic: str,
    payload: dict[str, Any],
    *,
    source_uri: str = "bos://governance/metaos_workflow",
    trace_id: str | None = None,
) -> str | None:
    """Publish through bus_foundation; return trace_id or None on failure."""
    try:
        from bus_foundation.facade import event as bus_event
    except ImportError as e:
        logger.debug("bus_foundation unavailable: %s", e)
        return None
    tid = trace_id or _get_trace_id() or f"metaos-{uuid.uuid4().hex[:8]}"
    try:
        bus_event.publish(
            topic=topic,
            payload=payload,
            source_uri=source_uri,
            trace_id=tid,
        )
        return tid
    except Exception as e:
        logger.warning("bus publish failed topic=%s: %s", topic, e)
        return None


def publish_via_http(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "metaos_workflow",
    target: str = "workflow",
    timeout: float = 2.0,
) -> bool:
    """Legacy Agora HTTP event plane."""
    try:
        requests.post(
            f"{_AGORA_API_URL}/v1/events",
            json={
                "source": source,
                "target": target,
                "event_type": event_type,
                "payload": payload,
            },
            headers={"Authorization": f"Bearer {_AGORA_TOKEN}"},
            timeout=timeout,
        )
        return True
    except Exception as e:
        logger.warning("HTTP event publish failed: %s", e)
        return False


def publish_node_event(
    workflow_id: str,
    node_id: str,
    status: str,
    payload: dict[str, Any] | None = None,
    *,
    task_type: str = "workflow",
) -> dict[str, Any]:
    """Unified publish for workflow node lifecycle events."""
    mode = event_bus_mode()
    body = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "status": status,
        **(payload or {}),
    }
    topic = f"node_{status}"
    result: dict[str, Any] = {"mode": mode, "bus": False, "http": False, "trace_id": None}

    if mode == "off":
        return result

    if mode in {"bus", "both"}:
        tid = publish_via_bus(topic, body)
        if tid:
            result["bus"] = True
            result["trace_id"] = tid

    if mode in {"http", "both"} or (mode == "bus" and not result["bus"]):
        # bus-only failure falls back to http when mode=bus? keep strict: only both/http
        if mode in {"http", "both"}:
            result["http"] = publish_via_http(topic, body, target=task_type or "workflow")
        elif mode == "bus" and not result["bus"]:
            logger.warning("bus-only mode failed; not falling back to HTTP")

    return result


def publish_human_approval_event(
    workflow_id: str,
    node_id: str,
    reason: str,
    *,
    approve_cmd: str = "",
) -> dict[str, Any]:
    payload = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "reason": reason,
        "approve_cmd": approve_cmd or f"metaos approve {workflow_id}",
    }
    mode = event_bus_mode()
    result: dict[str, Any] = {"mode": mode, "bus": False, "http": False}
    if mode == "off":
        return result
    if mode in {"bus", "both"}:
        tid = publish_via_bus("human_approval_required", payload)
        result["bus"] = bool(tid)
        result["trace_id"] = tid
    if mode in {"http", "both"}:
        result["http"] = publish_via_http("human_approval_required", payload, target="human")
    return result


# Back-compat re-export for metaos_bus_adapter consumers
__all__ = [
    "event_bus_mode",
    "publish_node_event",
    "publish_human_approval_event",
    "publish_via_bus",
    "publish_via_http",
]
