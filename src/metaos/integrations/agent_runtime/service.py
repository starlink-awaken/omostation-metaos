"""MetaOS-governed lifecycle for provider execution sessions."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from metaos.core.types import AssetLevel, Decision, DecisionLevel, DigitalAsset, Task

from .contracts import AgentSession, ExecutionMode, OperationalRisk, SessionStatus, validate_session_policy
from .provider_context import ProviderLaunchContext, build_provider_context


class AgentRuntimeService:
    """Prepare and finalize agent sessions through the MetaOS system of record.

    The service is deliberately thin: it delegates authorization to the
    existing gate, persistence to DLayer, and anomaly observation to the
    existing immune monitor. Provider adapters never bypass this service.
    """

    def __init__(self, engine: Any):
        self.engine = engine

    def prepare(self, session: AgentSession, access_level: str = "owner") -> tuple[AgentSession, ProviderLaunchContext]:
        """Gate and persist a session before a provider can be launched."""
        violations = validate_session_policy(session)
        if violations:
            session.status = SessionStatus.BLOCKED
            session.gate_decision = DecisionLevel.RED.value
            session.gate_reason = "; ".join(violations)
            self._persist_session_asset(session, access_level)
            self._trace(session, "agent_session_blocked", session.gate_reason)
            return session, build_provider_context(session)

        task = Task(
            task_id=session.task_id,
            h_id=session.h_id or self.engine.current_h.h_id,
            task_type="agent_runtime",
            input=self._gate_input(session),
        )
        level, reason, _deadline = self.engine.gate.evaluate(task)
        session.gate_decision = level.value
        session.gate_reason = reason

        if self._must_block(session, level):
            session.status = SessionStatus.BLOCKED
        else:
            session.status = SessionStatus.PREPARED

        asset = self._persist_session_asset(session, access_level)
        session.asset_id = asset.asset_id
        decision = Decision(
            h_id=session.h_id or self.engine.current_h.h_id,
            level=level.value,
            action="blocked" if session.status == SessionStatus.BLOCKED else "prepared",
            description=f"agent_session:{session.session_id} {session.description[:80]}",
            assets_used=[asset.asset_id],
            access_level=access_level,
            outcome_pending_review=(level == DecisionLevel.YELLOW),
        )
        self.engine.d.save_decision(decision)
        session.decision_id = decision.decision_id
        self._trace(session, "agent_session_prepared", f"gate={level.value}; status={session.status.value}")

        if session.status == SessionStatus.PREPARED:
            session.status = SessionStatus.RUNNING
            self._persist_session_asset(session, access_level)
            self._trace(session, "agent_session_launched", f"provider={session.provider.value}")
        return session, build_provider_context(session, session_asset_path=f"asset:{session.asset_id}")

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
        session.result_summary = summary
        session.evidence = list(evidence or [])
        session.finalized_at = datetime.now(UTC)
        session.status = SessionStatus.FINALIZED if verification_passed else SessionStatus.FAILED
        asset = self._persist_session_asset(session, access_level)
        session.asset_id = asset.asset_id
        self._trace(
            session,
            "agent_session_finalized" if verification_passed else "agent_session_failed",
            f"verification_passed={verification_passed}; evidence_count={len(session.evidence)}",
        )
        try:
            recent = self.engine.d.get_decisions(self.engine.current_h.h_id, 10)
            principles = self.engine.d.get_principles()
            self.engine.immune.evaluate(self.engine.current_h.h_id, self._gate_input(session), recent, principles)
        except Exception:
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

    def _persist_session_asset(self, session: AgentSession, access_level: str) -> DigitalAsset:
        level = AssetLevel.PRIVATE if access_level in {"owner", "private"} else AssetLevel.SHARED
        asset = DigitalAsset(
            asset_id=session.asset_id or f"session-{session.session_id}",
            level=level,
            content=json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=True),
            summary=f"AgentSession {session.session_id}: {session.status.value}",
            source_h_id=session.h_id or self.engine.current_h.h_id,
            asset_type="structured",
            tags=["agent_session", session.provider.value, session.risk.value, session.mode.value],
        )
        self.engine.d.save_asset(asset)
        return asset

    def _trace(self, session: AgentSession, event: str, detail: str) -> None:
        try:
            self.engine.d.append_trace_log(session.session_id, event, detail)
        except Exception:
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
                "scope": session.scope,
                "exclusions": session.exclusions,
                "success_criteria": session.success_criteria,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
