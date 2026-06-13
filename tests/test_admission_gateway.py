from metaos.layers.admission_gateway import AdmissionGateway


def test_admission_gateway_accepts_fully_declared_request():
    gateway = AdmissionGateway()

    result = gateway.evaluate_admission(
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
    assert result["reasons"] == ["All 5 governance components satisfied."]


def test_admission_gateway_rejects_missing_requirements_and_dangerous_capability():
    gateway = AdmissionGateway()

    result = gateway.evaluate_admission(
        {
            "domain": "memory",
            "role": "unknown",
            "declared_values": ["objective"],
            "supports_otlp": False,
            "omo_audit_trail_id": "",
            "capabilities": ["bypass_sandbox"],
        }
    )

    assert result["status"] == "rejected"
    assert any("Value Alignment" in reason for reason in result["reasons"])
    assert any("Permission Isolation" in reason for reason in result["reasons"])
    assert any("Process Monitoring" in reason for reason in result["reasons"])
    assert any("Traceability" in reason for reason in result["reasons"])
    assert any("Circuit Breaker" in reason for reason in result["reasons"])
