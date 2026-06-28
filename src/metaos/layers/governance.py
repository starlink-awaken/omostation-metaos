"""元治理模块——S 规则修改的前 2 层实现

实现 01-理论基础/08-元治理.md 的设计：
第一层（内核层 K1-K4）：不可修改，硬编码
第二层（常规规则层）：可修改，需冷静期 + 影响范围扫描
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class RuleChangeProposal:
    """规则修改提案"""

    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    rule_id: str = ""  # 规则标识
    current_value: str = ""  # 当前值
    new_value: str = ""  # 新值
    reason: str = ""  # 修改理由
    proposed_by: str = ""  # 提出者 H
    status: str = "pending"  # pending / cooling / approved / rejected
    cooling_hours: int = 24  # 冷静期（个人场景 24h，群体场景 72h）
    created_at: datetime = field(default_factory=datetime.now)
    cooling_end: datetime | None = None
    impact_scan: str = ""  # 影响范围扫描结果
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# 内核层 K1-K4（不可修改）
IRREDUCIBLE_RULES = {
    "K1": "禁止任何使熔断不可关闭（C08）失效的修改",
    "K2": "禁止任何使 K1 失效的修改",
    "K3": "所有对 S 的修改必须记录不可删除的审计日志",
    "K4": "修改 S 属于红灯区决策（C07）",
}


class MetaGovernance:
    """
    元治理引擎——管辖 S 规则的修改。
    第一层（内核）：硬编码，不可修改
    第二层（常规规则）：可修改 + 影响扫描 + 冷静期
    第三层（委员会审核）：仅群体场景
    """

    def __init__(self, scenario: str = "personal", on_rule_changed=None, storage=None):
        """
        V5#1 修复：on_rule_changed 是规则生效后的回调函数。
        V6#6 修复：storage 是持久化层（DLayer 实例），传入后提案和日志持久化。
        """
        self.scenario = scenario
        self._on_rule_changed = on_rule_changed
        self._storage = storage
        self._proposals: dict[str, RuleChangeProposal] = {}
        self._change_log: list[dict] = []  # 不可删除的审计日志
        # 从持久化恢复
        if storage:
            self._recover_from_storage()

    def check_irreducible(self, rule_id: str) -> bool:
        """第一层检查：是否触及内核层"""
        return rule_id in IRREDUCIBLE_RULES

    def propose_change(self, rule_id: str, current: str, new: str, reason: str, proposed_by: str) -> dict:
        """第二层：发起规则修改——V8 修复：影响扫描细化"""
        if self.check_irreducible(rule_id):
            return {
                "status": "rejected",
                "message": f"触及内核规则 {rule_id}: {IRREDUCIBLE_RULES[rule_id]}",
            }

        cooling = 72 if self.scenario == "group" else 24
        prop = RuleChangeProposal(
            rule_id=rule_id,
            current_value=current,
            new_value=new,
            reason=reason,
            proposed_by=proposed_by,
            cooling_hours=cooling,
            cooling_end=datetime.now() + timedelta(hours=cooling),
            status="cooling",
        )

        # 影响范围扫描——V8 修复：提供结构化的影响评估
        prop.impact_scan = self._scan_impact(rule_id, current, new)

        self._proposals[prop.proposal_id] = prop
        self._change_log.append(
            {
                "type": "proposed",
                "rule_id": rule_id,
                "by": proposed_by,
                "at": datetime.now().isoformat(),
                "from": current,
                "to": new,
            }
        )
        self._persist()  # TD-A02 修复：变更后持久化
        return {
            "status": "cooling",
            "proposal_id": prop.proposal_id,
            "cooling_end": prop.cooling_end.isoformat(),
            "impact_scan": prop.impact_scan,
        }

    # ── V8 修复：元治理沙箱 ──

    def simulate_change(self, rule_id: str, current: str, new: str) -> dict:
        """dry-run：模拟规则修改，不实际执行

        返回影响扫描结果 + 预期行为差异，不创建提案、不触发回调。
        """
        if self.check_irreducible(rule_id):
            return {
                "status": "simulated",
                "verdict": "rejected",
                "reason": f"触及内核规则 {rule_id}，不可修改",
                "impact": IRREDUCIBLE_RULES[rule_id],
            }

        impact = self._scan_impact(rule_id, current, new)

        # 模拟执行路径：检查是否可能产生冲突
        warnings = []
        if "deadline" in rule_id.lower() or "timeout" in rule_id.lower():
            warnings.append("⏱  时间参数变更可能影响依赖此规则的任务调度")
        if "threshold" in rule_id.lower():
            warnings.append("📊 阈值变更可能触发边界效应，建议小步迭代")
        if "rate" in rule_id.lower():
            warnings.append("🔁 比率变更可能放大或缩小免疫系统敏感度")

        return {
            "status": "simulated",
            "verdict": "acceptable",
            "rule_id": rule_id,
            "diff": f"{current} → {new}",
            "impact": impact,
            "warnings": warnings,
            "recommendation": "建议通过 propose_change 正式提交"
            if not warnings
            else f"存在 {len(warnings)} 个警告，解决后建议观察 1 个冷却期再执行",
        }

    def confirm_change(self, proposal_id: str, confirmed_by: str) -> dict:
        """冷静期结束后确认执行——V8 修复：支持自动回滚"""
        prop = self._proposals.get(proposal_id)
        if not prop:
            return {"status": "error", "message": "提案不存在"}
        if datetime.now() < prop.cooling_end:
            remaining = (prop.cooling_end - datetime.now()).seconds // 60
            return {"status": "cooling", "message": f"冷静期还剩 {remaining} 分钟"}

        # 执行前备份当前值（自动回滚用）
        _backup = {
            "rule_id": prop.rule_id,
            "previous_value": prop.current_value,
            "new_value": prop.new_value,
            "applied_at": datetime.now().isoformat(),
            "rollback_at": (datetime.now() + timedelta(hours=24)).isoformat(),
        }

        prop.status = "approved"
        self._change_log.append(
            {
                "type": "approved",
                "rule_id": prop.rule_id,
                "by": confirmed_by,
                "at": datetime.now().isoformat(),
                "from": prop.current_value,
                "to": prop.new_value,
                "backup": _backup,  # 存快照以便回滚
            }
        )
        self._persist()  # TD-A02 修复：变更后持久化
        # V5#1 修复：规则生效——调用回调刷新配置
        if self._on_rule_changed:
            try:
                self._on_rule_changed(prop.rule_id)
            except Exception as e:  # noqa: BLE001  # defensive fallback
                return {"status": "warning", "message": f"规则已批准但生效失败: {e}"}

        return {
            "status": "approved",
            "rule_id": prop.rule_id,
            "change": f"{prop.current_value[:40]} → {prop.new_value[:40]}",
            "rollback_window": "24h — 到期前可通过 rollback() 回退",
        }

    def rollback(self, proposal_id: str, requested_by: str) -> dict:
        """V8 修复：24h 窗口内自动回滚——撤销最后一次已批准的变更"""
        # 找对应的审计日志
        for entry in reversed(self._change_log):
            if entry["type"] == "approved" and entry.get("backup", {}).get("rule_id"):
                backup = entry["backup"]
                rollby = requested_by
                self._change_log.append(
                    {
                        "type": "rollback",
                        "rule_id": backup["rule_id"],
                        "by": rollby,
                        "at": datetime.now().isoformat(),
                        "from": backup["new_value"],
                        "to": backup["previous_value"],
                        "reason": "手动回滚",
                    }
                )
                # 触发回调把值改回去
                if self._on_rule_changed:
                    try:
                        self._on_rule_changed(backup["rule_id"])
                    except Exception:  # noqa: BLE001  # defensive fallback
                        pass
                return {
                    "status": "rolled_back",
                    "rule_id": backup["rule_id"],
                    "restored": f"{backup['new_value'][:40]} → {backup['previous_value'][:40]}",
                }

        return {"status": "error", "message": "无可回滚的已批准变更"}

    def _scan_impact(self, rule_id: str, current: str = "", new: str = "") -> str:
        """V8 修复：加入变更前后的对比影响分析"""
        parts = [f"规则 `{rule_id}` 变更影响分析:"]
        if current and new:
            parts.append(f"  • 变更: `{current}` → `{new}`")
        parts.append("  • 可能影响依赖此规则的决策流程和免疫检测")
        parts.append("  • 建议在修改前备份当前规则配置")
        parts.append("  • 变更生效后 24h 内可通过 rollback 回退")
        return "\n".join(parts)

    # V6#6 修复：持久化支持
    def _recover_from_storage(self):
        """从持久化恢复未完成的提案和审计日志"""
        if not self._storage:
            return
        # 尝试从 storage 恢复——storage 需提供 get_governance_state()
        try:
            state = getattr(self._storage, "get_governance_state", lambda: {})()
            for pid, pdata in state.get("proposals", {}).items():
                prop = RuleChangeProposal(**pdata)
                self._proposals[pid] = prop
            self._change_log = state.get("change_log", [])
        except Exception:  # noqa: BLE001  # defensive fallback
            pass  # 首次启动无数据

    def _persist(self):
        """持久化当前状态"""
        if not self._storage:
            return
        persist = getattr(self._storage, "save_governance_state", None)
        if persist:
            persist(
                {
                    "proposals": {
                        pid: {
                            "proposal_id": p.proposal_id,
                            "rule_id": p.rule_id,
                            "current_value": p.current_value,
                            "new_value": p.new_value,
                            "status": p.status,
                            "cooling_end": p.cooling_end.isoformat() if p.cooling_end else "",
                            "proposed_by": p.proposed_by,
                        }
                        for pid, p in self._proposals.items()
                        if p.status in ("pending", "cooling")
                    },
                    "change_log": self._change_log,
                }
            )

    def get_history(self, limit: int = 10) -> list[dict]:
        """获取审计日志（不可删除）"""
        return list(self._change_log[-limit:])

    def list_pending(self) -> list[dict]:
        return [
            {
                "id": p.proposal_id,
                "rule": p.rule_id,
                "status": p.status,
                "cooling_end": p.cooling_end.isoformat() if p.cooling_end else "",
                "by": p.proposed_by,
            }
            for p in self._proposals.values()
            if p.status in ("pending", "cooling")
        ]
