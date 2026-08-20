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
    # PROVIDER 与新建实例均为默认 observe 模式 (ADR-0252 2 周观察窗):
    # 危险请求软放行 (admitted_with_warnings + would_reject), 语义一致
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
    fresh = MetaOSAdmissionProvider().evaluate(
        {
            "domain": "memory",
            "role": "unknown",
            "declared_values": [],
            "supports_otlp": False,
            "omo_audit_trail_id": "",
            "capabilities": ["bypass_sandbox"],
        }
    )
    assert result["status"] == "admitted_with_warnings"
    assert result["status"] == fresh["status"]
    assert result["would_reject"] is True
