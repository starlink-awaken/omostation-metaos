"""ADR-0252 O-D4: admit observe vs blocking."""

from __future__ import annotations

from metaos.layers.admission_gateway import AdmissionGateway


def _bad_request() -> dict:
    return {
        "domain": "test",
        "role": "not-a-role",
        "declared_values": [],
        "supports_otlp": False,
        "capabilities": [],
    }


def test_observe_mode_soft_pass() -> None:
    gw = AdmissionGateway(mode="observe")
    r = gw.evaluate_admission(_bad_request())
    assert r["status"] == "admitted_with_warnings"
    assert r.get("would_reject") is True
    assert r["mode"] == "observe"


def test_blocking_mode_rejects() -> None:
    gw = AdmissionGateway(mode="blocking")
    r = gw.evaluate_admission(_bad_request())
    assert r["status"] == "rejected"
    assert r["mode"] == "blocking"


def test_good_request_admitted() -> None:
    gw = AdmissionGateway(mode="blocking")
    r = gw.evaluate_admission(
        {
            "domain": "test",
            "role": "generator",
            "declared_values": ["human-centric", "objective", "transparent"],
            "supports_otlp": True,
            "omo_audit_trail_id": "audit-1",
            "capabilities": [],
        }
    )
    assert r["status"] == "admitted"
