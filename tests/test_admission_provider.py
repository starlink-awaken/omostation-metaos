"""MetaOS AdmissionPort provider tests."""

from metaos.integrations.admission_provider import PROVIDER, MetaOSAdmissionProvider


def test_provider_admits_full_request():
    p = MetaOSAdmissionProvider()
    result = p.evaluate(
        {
            "domain": "analysis",
            "role": "generator",
            "declared_values": ["human-centric", "objective", "transparent"],
            "supports_otlp": True,
            "omo_audit_trail_id": "audit-123",
            "capabilities": ["read_only"],
        }
    )
    assert result["status"] == "admitted"


def test_provider_singleton_same_semantics():
    result = PROVIDER.evaluate(
        {
            "domain": "memory",
            "role": "unknown",
            "declared_values": [],
            "supports_otlp": False,
            "omo_audit_trail_id": "",
            "capabilities": ["bypass_sandbox"],
        }
    )
    assert result["status"] == "rejected"
