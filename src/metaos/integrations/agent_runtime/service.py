"""MetaOS-governed lifecycle for provider execution sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from metaos.core.types import AssetLevel, Decision, DecisionLevel, DigitalAsset, Task

from .capabilities import validate_capability_profile
from .contracts import (
    AgentSession,
    ConfirmationStatus,
    ExecutionMode,
    OperationalRisk,
    SessionStatus,
    validate_session_policy,
)
from .provider_context import (
    ProviderLaunchContext,
    build_blocked_provider_context,
    build_provider_context,
)


class AgentRuntimeService:
    """Prepare and finalize agent sessions through the MetaOS system of record.

    This service delegates authorization to the existing gate, persistence to
    DLayer, and anomaly observation to the existing immune monitor. Provider
    adapters never decide gate outcomes or claim completion on their own.
    """

    def __init__(self, engine: Any):
        self.engine = engine

    def prepare(self, session: AgentSession, access_level: str = "owner") -> tuple[AgentSession, ProviderLaunchContext]:
        """Gate and persist a session before a provider can be launched.

        A successful return with `prepared` means launch is permitted. It does
        not mean the provider process has started.
        """
        violations = [*validate_session_policy(session), *validate_capability_profile(session)]
        if violations:
            session.status = SessionStatus.BLOCKED
            session.gate_decision = DecisionLevel.RED.value
            session.gate_reason = "; ".join(violations)
            session.confirmation_status = ConfirmationStatus.NOT_REQUIRED
            self._persist_session_asset(session, access_level)
            decision = self._save_decision(session, DecisionLevel.RED, access_level, action="blocked")
            session.decision_id = decision.decision_id
            self._persist_session_asset(session, access_level)
            self._trace(session, "agent_session_blocked", session.gate_reason)
            return session, build_blocked_provider_context(
                session,
                session_asset_path=f"asset:{session.asset_id}",
                reason=session.gate_reason,
            )

        task = Task(
            task_id=session.task_id,
            h_id=session.h_id or self.engine.current_h.h_id,
            task_type="agent_runtime",
            input=self._gate_input(session),
        )
        level, reason, _deadline = self.engine.gate.evaluate(task)
        session.gate_decision = level.value
        session.gate_reason = reason
        session.confirmation_status = (
            ConfirmationStatus.PENDING if level == DecisionLevel.YELLOW else ConfirmationStatus.NOT_REQUIRED
        )
        session.status = SessionStatus.BLOCKED if self._must_block(session, level) else SessionStatus.PREPARED

        self._persist_session_asset(session, access_level)
        decision = self._save_decision(
            session, level, access_level, action="blocked" if session.status == SessionStatus.BLOCKED else "prepared"
        )
        session.decision_id = decision.decision_id
        self._persist_session_asset(session, access_level)
        self._trace(session, "agent_session_prepared", f"gate={level.value}; status={session.status.value}")
        return session, build_provider_context(session, session_asset_path=f"asset:{session.asset_id}")

    def approve(self, session: AgentSession, *, comment: str = "", access_level: str = "owner") -> AgentSession:
        """Persist human approval for a yellow session across CLI processes."""
        if session.gate_decision != DecisionLevel.YELLOW.value or not session.decision_id:
            raise ValueError("Only a persisted yellow-gate session can be approved.")
        self._save_confirmation_decision(session, access_level, action="approved")
        session.confirmation_status = ConfirmationStatus.APPROVED
        session.status = SessionStatus.PREPARED
        self._persist_session_asset(session, access_level)
        self._trace(session, "agent_session_h_approved", comment)
        return session

    def reject(self, session: AgentSession, *, comment: str = "", access_level: str = "owner") -> AgentSession:
        """Persist human rejection for a yellow session across CLI processes."""
        if session.gate_decision != DecisionLevel.YELLOW.value or not session.decision_id:
            raise ValueError("Only a persisted yellow-gate session can be rejected.")
        self._save_confirmation_decision(session, access_level, action="rejected")
        session.confirmation_status = ConfirmationStatus.REJECTED
        session.status = SessionStatus.CANCELLED
        self._persist_session_asset(session, access_level)
        self._trace(session, "agent_session_h_rejected", comment)
        return session

    def mark_running(self, session: AgentSession, access_level: str = "owner") -> AgentSession:
        """Record provider process launch only after the adapter has actually launched it."""
        if session.status != SessionStatus.PREPARED:
            raise ValueError(f"Cannot mark session running from status {session.status.value}.")
        if (
            session.gate_decision == DecisionLevel.YELLOW.value
            and session.confirmation_status != ConfirmationStatus.APPROVED
        ):
            raise ValueError("Yellow-gate session requires human approval before provider launch.")
        session.status = SessionStatus.RUNNING
        self._persist_session_asset(session, access_level)
        self._trace(session, "agent_session_launched", f"provider={session.provider.value}")
        return session

    def finalize(
        self,
        session: AgentSession,
        *,
        summary: str,
        evidence: list[str] | None = None,
        verification_passed: bool = False,
        access_level: str = "owner",
    ) -> AgentSession:
        """Persist actual outcome and trace it; never infer success from launch."""
        if session.status not in {SessionStatus.PREPARED, SessionStatus.RUNNING}:
            raise ValueError(f"Cannot finalize session from status {session.status.value}.")
        session.result_summary = summary
        session.evidence = list(evidence or [])
        session.finalized_at = datetime.now(UTC)
        session.status = SessionStatus.FINALIZED if verification_passed else SessionStatus.FAILED
        self._persist_session_asset(session, access_level)
        self._trace(
            session,
            "agent_session_finalized" if verification_passed else "agent_session_failed",
            f"verification_passed={verification_passed}; evidence_count={len(session.evidence)}",
        )
        try:
            recent = self.engine.d.get_decisions(self.engine.current_h.h_id, 10)
            principles = self.engine.d.get_principles()
            self.engine.immune.evaluate(self.engine.current_h.h_id, self._gate_input(session), recent, principles)
        except Exception:  # defensive fallback  # noqa: BLE001
            pass
        return session

    def _must_block(self, session: AgentSession, level: DecisionLevel) -> bool:
        if level == DecisionLevel.RED:
            return True
        if level == DecisionLevel.YELLOW and session.mode == ExecutionMode.COMMIT:
            return True
        if session.risk == OperationalRisk.R4 and level != DecisionLevel.GREEN:
            return True
        return False

    def _save_decision(self, session: AgentSession, level: DecisionLevel, access_level: str, action: str) -> Decision:
        decision = Decision(
            h_id=session.h_id or self.engine.current_h.h_id,
            level=level.value,
            action=action,
            description=f"agent_session:{session.session_id} {session.description[:80]}",
            assets_used=[session.asset_id],
            access_level=access_level,
            outcome_pending_review=(level == DecisionLevel.YELLOW),
        )
        self.engine.d.save_decision(decision)
        return decision

    def _save_confirmation_decision(self, session: AgentSession, access_level: str, action: str) -> None:
        decision = Decision(
            decision_id=session.decision_id,
            h_id=session.h_id or self.engine.current_h.h_id,
            level=DecisionLevel.YELLOW.value,
            action=action,
            description=f"agent_session:{session.session_id} {session.description[:80]}",
            assets_used=[session.asset_id],
            access_level=access_level,
            outcome_pending_review=False,
        )
        self.engine.d.save_decision(decision)

    def _persist_session_asset(self, session: AgentSession, access_level: str) -> DigitalAsset:
        from .integrity import attach_integrity

        level = AssetLevel.PRIVATE if access_level in {"owner", "private"} else AssetLevel.SHARED
        if not session.asset_id:
            session.asset_id = f"session-{session.session_id}"
        payload = attach_integrity(session.to_dict())
        session.integrity_hmac = payload.get("integrity_hmac", "")
        asset = DigitalAsset(
            asset_id=session.asset_id,
            level=level,
            content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            summary=f"AgentSession {session.session_id}: {session.status.value}",
            source_h_id=session.h_id or self.engine.current_h.h_id,
            asset_type="structured",
            tags=["agent_session", session.provider.value, session.risk.value, session.mode.value],
        )
        self.engine.d.save_asset(asset)
        self.engine.d.write_asset_trace(
            asset.asset_id,
            asset.level.value if hasattr(asset.level, "value") else str(asset.level),
            asset.source_h_id,
            summary=asset.summary,
        )
        session.asset_id = asset.asset_id
        return asset

    def _trace(self, session: AgentSession, event: str, detail: str) -> None:
        try:
            self.engine.d.append_trace_log(session.asset_id or f"session-{session.session_id}", event, detail)
        except Exception:  # defensive fallback  # noqa: BLE001
            pass

    @staticmethod
    def _gate_input(session: AgentSession) -> str:
        return json.dumps(
            {
                "kind": "agent_session",
                "description": session.description,
                "provider": session.provider.value,
                "risk": session.risk.value,
                "mode": session.mode.value,
                "capability_profile": session.capability.profile,
                "capability_requested": session.capability.requested,
                "scope": session.scope,
                "exclusions": session.exclusions,
                "success_criteria": session.success_criteria,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
