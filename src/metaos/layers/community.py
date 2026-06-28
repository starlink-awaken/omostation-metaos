"""群体场景引擎——多 H 协作 + 社区协议"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class VoteType(Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ProposalStatus(Enum):
    PENDING = "pending"  # 等待投票
    APPROVED = "approved"  # 通过
    REJECTED = "rejected"  # 被拒
    EXPIRED = "expired"  # 超时
    IMPLEMENTED = "implemented"  # 已执行


class ConflictStatus(Enum):
    OPEN = "open"
    IN_ARBITRATION = "in_arbitration"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


@dataclass
class Proposal:
    """D_共有 资产提案"""

    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    content: str = ""
    proposer_h: str = ""
    status: ProposalStatus = ProposalStatus.PENDING
    votes_for: int = 0
    votes_against: int = 0
    votes_abstain: int = 0
    voter_h_ids: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


@dataclass
class ConflictEntry:
    """价值冲突登记簿条目"""

    conflict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    asset_id: str = ""
    h_a_id: str = ""
    h_b_id: str = ""
    h_a_position: str = ""
    h_b_position: str = ""
    status: ConflictStatus = ConflictStatus.OPEN
    arbiter_h_id: str = ""
    resolution: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


@dataclass
class CommitteeMember:
    h_id: str
    role: str = "member"  # member / chair / auditor
    joined_at: datetime = field(default_factory=datetime.now)
    term_end: datetime | None = None
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


class CommunityEngine:
    """
    群体场景引擎——在 SEngine 之上封装社区协议层。
    管理多 H 的 D_共有 写入/修改/投票/仲裁。
    """

    def __init__(self, on_proposal_approved=None, on_conflict_resolved=None):
        self._proposals: dict[str, Proposal] = {}
        self._conflicts: dict[str, ConflictEntry] = {}
        self._committee: dict[str, CommitteeMember] = {}
        self._min_committee_size = 3
        self._approval_rate = 0.6
        self._delete_approval_rate = 0.8
        self._registered_h: set[str] = set()
        self._vote_lock = threading.Lock()
        self._pending_invites: list[str] = []
        # B-01 修复：回调通知 SEngine
        self._on_proposal_approved = on_proposal_approved
        self._on_conflict_resolved = on_conflict_resolved

    # ── H 注册 ──

    def register_h(self, h_id: str, role: str = "member") -> dict:
        """注册一个新 H 到群体场景"""
        if h_id in self._registered_h:
            return {"status": "error", "message": "H 已注册"}

        self._registered_h.add(h_id)
        self._committee[h_id] = CommitteeMember(h_id=h_id, role=role, term_end=datetime.now() + timedelta(days=365))
        return {"status": "ok", "message": f"{h_id} 已注册", "members": len(self._registered_h)}

    def unregister_h(self, h_id: str, inherit_to: str = "") -> dict:
        """注销 H，可选继承者"""
        if h_id not in self._registered_h:
            return {"status": "error", "message": "H 未注册"}
        self._registered_h.discard(h_id)
        self._committee.pop(h_id, None)
        return {"status": "ok", "message": f"{h_id} 已注销"}

    def list_members(self) -> list[dict]:
        return [
            {"h_id": m.h_id, "role": m.role, "term_end": m.term_end.isoformat() if m.term_end else "permanent"}
            for m in self._committee.values()
        ]

    # ── D_共有 提案流程（社区协议 协议1）──

    def propose_shared_asset(self, proposer: str, title: str, content: str, vote_hours: int = 72) -> Proposal:
        """提交一条 D_共有 资产提案"""
        if proposer not in self._registered_h:
            return {"status": "error", "message": "提案者未注册"}

        prop = Proposal(
            title=title,
            content=content,
            proposer_h=proposer,
            expires_at=datetime.now() + timedelta(hours=vote_hours),
        )
        self._proposals[prop.proposal_id] = prop
        return prop

    def vote_on_proposal(self, proposal_id: str, h_id: str, vote: VoteType) -> dict:
        """对提案投票"""
        with self._vote_lock:
            prop = self._proposals.get(proposal_id)
            if not prop:
                return {"status": "error", "message": "提案不存在"}
            if h_id not in self._registered_h:
                return {"status": "error", "message": "投票者未注册"}
            if h_id in prop.voter_h_ids:
                return {"status": "error", "message": "已投过票"}

            prop.voter_h_ids[h_id] = vote.value
        if vote == VoteType.APPROVE:
            prop.votes_for += 1
        elif vote == VoteType.REJECT:
            prop.votes_against += 1
        else:
            prop.votes_abstain += 1

        # 检查是否达到通过/拒绝阈值
        prop.votes_for + prop.votes_against
        required = max(
            len(self._registered_h) * self._approval_rate,
            2,  # 最少 2 票
        )

        if prop.votes_for >= required:
            prop.status = ProposalStatus.APPROVED
            # B-01 修复：提案通过 → 回调 SEngine 走 gate/immune 管道
            if self._on_proposal_approved:
                try:
                    self._on_proposal_approved(
                        {
                            "proposal_id": prop.proposal_id,
                            "title": prop.title,
                            "content": prop.content,
                            "proposer_h": prop.proposer_h,
                        }
                    )
                except Exception:  # defensive fallback  # noqa: BLE001
                    pass
        elif prop.votes_against >= required:
            prop.status = ProposalStatus.REJECTED
        elif datetime.now() > prop.expires_at:
            prop.status = ProposalStatus.EXPIRED

        return {
            "status": "ok",
            "proposal_id": proposal_id,
            "state": prop.status.value,
            "for": prop.votes_for,
            "against": prop.votes_against,
            "abstain": prop.votes_abstain,
        }

    def list_proposals(self, status: str = "") -> list[dict]:
        result = []
        for pid, p in self._proposals.items():
            if status and p.status.value != status:
                continue
            result.append(
                {
                    "id": pid,
                    "title": p.title[:40],
                    "proposer": p.proposer_h,
                    "status": p.status.value,
                    "for": p.votes_for,
                    "against": p.votes_against,
                    "deadline": p.expires_at.isoformat(),
                }
            )
        return sorted(result, key=lambda x: x.get("deadline", ""))

    # ── 价值冲突登记（协议2）──

    def register_conflict(self, asset_id: str, h_a: str, h_b: str, pos_a: str, pos_b: str) -> ConflictEntry:
        """登记价值冲突"""
        conflict = ConflictEntry(
            asset_id=asset_id,
            h_a_id=h_a,
            h_b_id=h_b,
            h_a_position=pos_a,
            h_b_position=pos_b,
            arbiter_h_id=self._select_arbiter(h_a, h_b),
        )
        self._conflicts[conflict.conflict_id] = conflict
        return conflict

    def _select_arbiter(self, h_a: str, h_b: str) -> str:
        """选择仲裁者——委员会中非冲突方成员"""
        for member in self._committee.values():
            if member.h_id not in (h_a, h_b) and member.role in ("chair", "member"):
                return member.h_id
        return ""  # 无可仲裁者

    def resolve_conflict(self, conflict_id: str, resolution: str) -> dict:
        """解决冲突——B-01 修复：回调触发免疫检测"""
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            return {"status": "error", "message": "冲突不存在"}
        conflict.status = ConflictStatus.RESOLVED
        conflict.resolution = resolution
        # B-01 修复：仲裁结论 → 回调 SEngine 触发免疫检测
        if self._on_conflict_resolved:
            try:
                self._on_conflict_resolved(
                    {
                        "conflict_id": conflict.conflict_id,
                        "resolution": resolution,
                        "arbiter_h_id": conflict.arbiter_h_id,
                    }
                )
            except Exception:  # defensive fallback  # noqa: BLE001
                pass
        return {
            "status": "ok",
            "conflict_id": conflict_id,
            "resolution": resolution,
        }

    def list_conflicts(self, status: str = "") -> list[dict]:
        result = []
        for cid, c in self._conflicts.items():
            if status and c.status.value != status:
                continue
            result.append(
                {
                    "id": cid,
                    "asset": c.asset_id[:12],
                    "h_a": c.h_a_id,
                    "h_b": c.h_b_id,
                    "status": c.status.value,
                    "arbiter": c.arbiter_h_id,
                }
            )
        return result

    # ── 委员会管理（协议3）──

    def rotate_chair(self) -> dict:
        """轮值主席——委员会内部轮换"""
        members = [m for m in self._committee.values() if m.role == "member"]
        current_chair = [m for m in self._committee.values() if m.role == "chair"]

        if current_chair:
            current_chair[0].role = "member"

        if members:
            # 简单轮换：选第一个 member 当新 chair
            new_chair = sorted(members, key=lambda m: m.joined_at)[0]
            new_chair.role = "chair"
            return {
                "status": "ok",
                "new_chair": new_chair.h_id,
                "rotation_type": "scheduled",
            }
        return {"status": "error", "message": "无可用成员"}

    def audit_log(self, limit: int = 10) -> list[dict]:
        """审计员日志"""
        return self.list_proposals()[:limit] + self.list_conflicts()[:limit]

    # ── 涌现条件检查（系统论·五论 P0）──

    def check_emergence_conditions(self, d_shared_count: int = 0) -> dict:
        """
        检查集体智能涌现的五项门槛。
        参考 04-场景特化/02-群体场景.md 的涌现条件。
        """
        h_count = len(self._registered_h)
        approved_proposals = sum(
            1 for p in self._proposals.values() if p.status in (ProposalStatus.APPROVED, ProposalStatus.IMPLEMENTED)
        )
        resolved_conflicts = sum(1 for c in self._conflicts.values() if c.status == ConflictStatus.RESOLVED)

        recent_votes = list(self._proposals.values())[-3:]
        consensus_ok = False
        if len(recent_votes) >= 2:
            consensus_count = sum(1 for v in recent_votes if v.votes_for / max(v.votes_for + v.votes_against, 1) > 0.6)
            consensus_ok = consensus_count >= 2

        results = {
            "h_count": {"value": h_count, "threshold": 3, "met": h_count >= 3},
            "d_shared_count": {"value": d_shared_count, "threshold": 50, "met": d_shared_count >= 50},
            "resolved_arbitrations": {"value": resolved_conflicts, "threshold": 3, "met": resolved_conflicts >= 3},
            "at_least_one_decision_benefited": {
                "value": approved_proposals,
                "threshold": 1,
                "met": approved_proposals >= 1,
            },
            "consensus_in_recent_3_votes": {"value": consensus_ok, "threshold": True, "met": consensus_ok},
        }

        all_met = all(r["met"] for r in results.values())
        return {
            "emergence_detected": all_met,
            "met_count": sum(1 for r in results.values() if r["met"]),
            "total_conditions": len(results),
            "details": results,
            "note": "门槛是必要条件不是充分条件。达标需额外定性验证。" if all_met else "未达标，集体智能不会涌现。",
        }
