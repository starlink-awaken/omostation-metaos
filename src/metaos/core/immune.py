"""免疫监控器——偏误检测 + 三层免疫"""

from metaos.core.types import Decision, ImmuneLevel  # type: ignore[import-not-found]


class ImmuneMonitor:
    """
    三层免疫机制。
    - 第一层（提醒）：可驳回
    - 第二层（冻结）：累计超阈值自动只读
    - 第三层（熔断）：核心价值观冲突，强制降级
    """

    def __init__(self):
        # 按 H 统计驳回计数
        self._dismissal_count: dict[str, int] = {}
        # 冻结状态
        self._frozen: set[str] = set()
        # 熔断状态
        self._meltdown: set[str] = set()

        # V-014 修复：H 认知状态上下文
        self._cognitive_state: dict[str, dict] = {}
        """{h_id: {energy: 1-10, emotion: str, date: str}}"""

        # 阈值
        self.WARNING_THRESHOLD = 3  # 同类提醒驳回 3 次 → 冻结
        self.MELTDOWN_THRESHOLD = 5  # 连续冲突 5 次 → 熔断

        # 语义噪声：接受质量检测（信息论·2026-05-20）
        self._accepted_bad: dict[str, list[dict]] = {}
        """H 接受了 M 建议但结果很差的历史。
        {h_id: [{decision_id, recommendation, outcome, timestamp}, ...]}"""

    def record_acceptance_outcome(self, h_id: str, decision_id: str, recommendation: str, outcome_quality: float):
        """
        记录一次接受后的结果质量（0=极差，1=极好）。
        当 H 接受了 M 的建议但 outcome_quality < 0.3 时，标记该建议为低质量。
        语义噪声检测——接受错误建议比驳回正确建议更危险（信息论#4.1）
        """
        if outcome_quality < 0.3:
            if h_id not in self._accepted_bad:
                self._accepted_bad[h_id] = []
            self._accepted_bad[h_id].append(
                {
                    "decision_id": decision_id,
                    "recommendation": recommendation[:40],
                    "outcome": outcome_quality,
                    "timestamp": __import__("datetime").datetime.now().isoformat(),
                }
            )
            return True
        return False

    def check_acceptance_quality(self, h_id: str) -> tuple[bool, str]:
        """
        检查接受质量异常。如果最近 10 次接受中有 > 3 次结果差，
        说明 M 的推荐质量在下降——触发的不是偏误提醒而是 M 降权信号。
        """
        bad_list = self._accepted_bad.get(h_id, [])[-10:]
        if len(bad_list) >= 3:
            return (
                True,
                f"⚠️ M 推荐质量下降: 最近 {len(bad_list)} 次接受中 "
                f"{sum(1 for b in bad_list if b['outcome'] < 0.3)} 次结果差，"
                f"建议审查 M 的 D_融合 资产或切换模型",
            )
        return (False, "")

    def metacognitive_quality_report(
        self, h_id: str, recent_decisions: list[Decision], self_assessments: list[dict]
    ) -> dict:
        """
        月度元认知质量报告（二阶控制论·2026-05-20）。
        分析 H 的元认知自评与决策质量的相关性。
        如果自评总是高分但决策质量低 → 元认知盲点。
        如果自评总是低分但决策质量高 → 自信不足。
        """
        if not recent_decisions or not self_assessments:
            return {"status": "insufficient_data"}

        avg_self_score = sum(a.get("score", 5) for a in self_assessments) / len(self_assessments)
        good_decisions = sum(1 for d in recent_decisions if not getattr(d, "outcome_pending_review", True))

        report = {
            "h_id": h_id,
            "self_assessment_avg": round(avg_self_score, 1),
            "recent_decision_count": len(recent_decisions),
            "closed_decision_count": good_decisions,
            "acceptance_quality_issues": len(self._accepted_bad.get(h_id, [])),
        }

        # 相关性诊断
        if avg_self_score >= 7 and good_decisions < len(recent_decisions) * 0.5:
            report["diagnosis"] = "⚠️ 元认知盲点风险——自评偏高但实际决策质量偏低"
        elif avg_self_score <= 4 and good_decisions >= len(recent_decisions) * 0.7:
            report["diagnosis"] = "ℹ️ 自信不足——实际表现不错但自评偏低"
        else:
            report["diagnosis"] = "✅ 元认知自评与决策质量一致"

        # 红队#1 加固：可验证声明（红队反击-深度分析方案）
        # 每条诊断附带具体的可验证例子，H 可在 ≤5 分钟内验证
        report["verifiable_claims"] = []
        if recent_decisions:
            # 取最近一个决策作为验证样本
            sample = recent_decisions[0]
            report["verifiable_claims"].append(
                {
                    "claim": f"最近决策「{sample.description[:30]}」的级别为{sample.level}，免疫触发为{sample.immune_triggered}",
                    "check_method": "在决策日志中查找此决策的原始记录，确认级别和免疫触发状态",
                    "expected_time_minutes": 2,
                }
            )
        if self._accepted_bad.get(h_id):
            worst = self._accepted_bad[h_id][-1]
            report["verifiable_claims"].append(
                {
                    "claim": f"最近一次接受质量差的事件：决策 {worst['decision_id'][:12]} 的结果评分为 {worst['outcome']}",
                    "check_method": "查找对应决策的原始描述和 outcome 记录",
                    "expected_time_minutes": 3,
                }
            )
        if self_assessments:
            report["verifiable_claims"].append(
                {
                    "claim": f"本月自评平均分 {report['self_assessment_avg']}，对应的决策关闭数为 {good_decisions}",
                    "check_method": "对比本月日课记录中的自评分与对应的决策结果",
                    "expected_time_minutes": 3,
                }
            )

        return report

    def check_pattern_anomaly(
        self, h_id: str, recent_decisions: list[Decision], baseline_rejection_rate: float = 0.15
    ) -> tuple[bool, str]:
        """
        检查模式异常：如果 H 最近频繁驳回 M 推荐，触发提醒。
        提升自 04-资产污染推演。
        """
        if len(recent_decisions) < 5:
            return (False, "")

        rejected = sum(1 for d in recent_decisions if d.action == "rejected")
        rate = rejected / len(recent_decisions)

        if rate > baseline_rejection_rate * 2:
            return (
                True,
                f"⚠️ H 驳回率异常: {rate:.0%} (基线 {baseline_rejection_rate:.0%})，"
                f"建议排查 D_融合 资产是否存在隐含错误",
            )

        return (False, "")

    def check_principle_conflict(self, h_id: str, input_text: str, active_principles: list) -> tuple[bool, str]:
        """
        检测原则冲突——提升自 01-职业决策推演。
        """
        if len(active_principles) < 2:
            return (False, "")

        # 简单实现：检测输入中是否同时引用了两条以上的原则
        mentioned = [p for p in active_principles if any(w in input_text for w in p.content.split()[:5])]
        if len(mentioned) >= 2:
            return (True, f"⚠️ 原则冲突提醒: {mentioned[0].content[:30]} vs {mentioned[1].content[:30]}")

        return (False, "")

    def evaluate(
        self, h_id: str, input_text: str, recent_decisions: list[Decision], active_principles: list
    ) -> tuple[ImmuneLevel, str]:
        """
        综合评估当前免疫级别。
        返回 (级别, 原因)
        """

        # 先查是否已熔断
        if h_id in self._meltdown:
            return (ImmuneLevel.MELTDOWN, "熔断激活：所有决策需逐条手动确认")

        # 是否已冻结
        if h_id in self._frozen:
            return (ImmuneLevel.FREEZE, "冻结中：相关功能自动只读")

        # 检测模式异常
        anomaly, msg = self.check_pattern_anomaly(h_id, recent_decisions)
        if anomaly:
            return (ImmuneLevel.WARNING, msg)

        # 检测原则冲突
        conflict, msg2 = self.check_principle_conflict(h_id, input_text, active_principles)
        if conflict:
            return (ImmuneLevel.WARNING, msg2)

        return (ImmuneLevel.NONE, "")

    def record_dismissal(self, h_id: str, reasonable: bool = False):
        """
        记录 H 驳回了一次免疫提醒。
        V-009 修复：合理驳回（H 是对的，M 错了）不计入计数。
        """
        if reasonable:
            return False  # 合理驳回不计入
        self._dismissal_count[h_id] = self._dismissal_count.get(h_id, 0) + 1
        if self._dismissal_count[h_id] >= self.WARNING_THRESHOLD:
            self._frozen.add(h_id)
            return True
        return False

    # V5#7 修复：独立超时计数器
    def record_timeout(self, h_id: str) -> bool:
        """
        记录决策超时（H 未在时限内确认）。
        V6#5 修复：超时阈值 = 5（比驳回的 3 更宽容，H 可能只是忙）
        """
        if not hasattr(self, "_timeout_count"):
            self._timeout_count = {}
        self._timeout_count[h_id] = self._timeout_count.get(h_id, 0) + 1
        if self._timeout_count[h_id] >= 5:
            self._frozen.add(h_id)
            return True
        return False

    def trigger_meltdown(self, h_id: str):
        """触发熔断"""
        self._meltdown.add(h_id)

    def release_freeze(self, h_id: str):
        """释放冻结"""
        self._frozen.discard(h_id)
        self._dismissal_count[h_id] = 0

    def release_meltdown(self, h_id: str):
        """释放熔断"""
        self._meltdown.discard(h_id)

    # ── V4#7 修复：免疫衰减 ──
    def decay_immunity(self, h_id: str, days_since_last_dismissal: int):
        """
        定时衰减免疫级别。
        冻结后 7 天无新违规 → 自动降级为提醒
        冻结后 14 天无新违规 → 自动解除
        """
        if days_since_last_dismissal >= 14 and h_id in self._frozen:
            self.release_freeze(h_id)
            return "fully_recovered"
        elif days_since_last_dismissal >= 7 and h_id in self._frozen:
            # 保持冻结但降级提醒频率
            return "partially_decayed"
        return "unchanged"

    def is_frozen(self, h_id: str) -> bool:
        return h_id in self._frozen

    def is_meltdown(self, h_id: str) -> bool:
        return h_id in self._meltdown

    # ── V-013/V-014 修复：认知状态与未复盘检查 ──

    def update_cognitive_state(self, h_id: str, energy: int, emotion: str = "neutral"):
        """晨间自评记录——V-014 修复"""
        import datetime

        self._cognitive_state[h_id] = {
            "energy": max(1, min(10, energy)),
            "emotion": emotion,
            "date": datetime.date.today().isoformat(),
        }

    def get_cognitive_state(self, h_id: str) -> dict:
        """获取 H 当天的认知状态"""
        import datetime

        state = self._cognitive_state.get(h_id, {})
        today = datetime.date.today().isoformat()
        if state.get("date") != today:
            return {"energy": 5, "emotion": "unknown", "note": "今日未自评"}
        return state

    def check_unreviewed_actions(self, decisions: list) -> list:
        """V-013 修复：检查待复盘的决策"""
        unreviewed = [d for d in decisions if getattr(d, "outcome_pending_review", False)]
        # 也可检查"完成但未复盘"（决策已确认但无 outcome 记录）
        unreviewed += [
            d
            for d in decisions
            if not getattr(d, "outcome_pending_review", True) and not self._accepted_bad.get(getattr(d, "h_id", ""), [])
        ]
        return unreviewed[:5]  # 最多返回 5 条
