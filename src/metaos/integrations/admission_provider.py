"""MetaOS AdmissionPort provider for Agora SPI (方案 C / ADR-0181).

Implements agora.admission.AdmissionPort without requiring agora to
import metaos.layers.admission_gateway directly.
"""

from __future__ import annotations

from typing import Any

from metaos.layers.admission_gateway import AdmissionGateway


class MetaOSAdmissionProvider:
    """Wrap Decision Gateway as AdmissionPort.evaluate()."""

    def __init__(self, gateway: AdmissionGateway | None = None) -> None:
        self._gateway = gateway or AdmissionGateway()

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._gateway.evaluate_admission(request)


def get_provider() -> MetaOSAdmissionProvider:
    """Entry-point / factory helper."""
    return MetaOSAdmissionProvider()


# Singleton for "module:attr" soft load (agora.admission.port._SOFT_PROVIDERS)
PROVIDER = MetaOSAdmissionProvider()
