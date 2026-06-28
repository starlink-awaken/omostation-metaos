"""S 引擎主流程——编排引擎"""

import logging
import secrets
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from metaos.core.gate import DecisionGate  # type: ignore[import-not-found]
from metaos.core.immune import ImmuneMonitor  # type: ignore[import-not-found]
from metaos.core.router import Router  # type: ignore[import-not-found]
from metaos.core.types import (  # type: ignore[import-not-found]
    AssetLevel,
    Decision,
    DecisionLevel,
    DigitalAsset,
    H,
    ImmuneLevel,
    Task,
)
from metaos.layers.d_layer import DLayer  # type: ignore[import-not-found]
from metaos.layers.m_layer import MLayer  # type: ignore[import-not-found]

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("metaos.engine")


class SEngine:
    """
    S 编排引擎——H-M 交互的核心协议执行器。
    六步标准路径：权限判定 → 路由决策 → M 执行 → 免疫检测 → 结果组装 → H 确认
    """

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = str(Path.home() / ".metaos" / "data")
        self.router = Router()
        self.gate = DecisionGate()

        # 抖动保护——稳定窗口
        self._stable_window_enter = 3
        self._stable_window_exit = 5
        self._health_fail_count = 0
        self._health_pass_count = 0
        self._offline_mode = False
        self.immune = ImmuneMonitor()
        self.d = DLayer(data_dir)
        self.m = MLayer()

        # V-001 修复：H 身份映射表——V6#4 修复：含过期时间
        # V7.0 修复：从持久化恢复 sessions
        self._h_sessions: dict[str, dict] = {}
        self._current_h_id: str = ""
        self._restore_sessions()  # 从 SQLite 恢复历史 token

        # V6#7 修复：惰性创建 CommunityEngine
        self._community = None

        # V5#1 修复：元治理集成——V6#6 修复：传入 d 作为持久化层
        from metaos.layers.governance import MetaGovernance  # type: ignore[import-not-found]

        self.governance = MetaGovernance(
            scenario="personal",
            on_rule_changed=lambda rule_id: self.gate.reload(),
            storage=self.d,
        )

        # 黄灯待确认队列
        self._pending_yellow: list[Decision] = []
        # V4#9 修复：异常统计
        self._error_log: list[str] = []

    # ── V6#1 修复：Community → SEngine 运行时通道 ──

    def accept_community_proposal(self, proposal: dict) -> dict:
        """接受社区提案结果，走 SEngine 标准管道

        将已通过的社区提案写入 D_共有 资产 + 生成决策日志 + 触发免疫检测。
        """
        pid = proposal.get("proposal_id", "")
        title = proposal.get("title", "")
        content = proposal.get("content", "")
        proposer = proposal.get("proposer_h", "")

        # 1. 创建 D_共有 资产
        asset = DigitalAsset(
            level=AssetLevel.SHARED,
            content=content,
            summary=title,
            source_h_id=proposer,
            asset_type="text",
            tags=["community", "proposal"],
        )
        self.d.save_asset(asset)

        # 2. 走决策门控（社区提案默认共享）
        task = Task(task_id=pid, h_id=proposer, task_type="reasoning", input=f"[社区提案通过] {title}: {content[:100]}")
        try:
            level, reason, deadline = self.gate.evaluate(task)
        except Exception:  # defensive fallback  # noqa: BLE001
            level, _reason, _deadline = DecisionLevel.GREEN, "社区共识", None

        # 3. 生成决策日志
        decision = Decision(
            h_id=proposer,
            level=level.value,
            action="approved",
            description=f"社区提案通过: {title}",
            access_level="public",
        )
        self.d.save_decision(decision)

        # 4. 触发免疫检测
        recent = self.d.get_decisions(proposer, 10)
        principles = self.d.get_principles()
        immune_level, immune_msg = self.immune.evaluate(proposer, f"[社区提案] {title}", recent, principles)

        # 5. 溯源
        self.d.append_trace_log(pid, "community_approved", f"proposal={title} immune={immune_level.value}")

        return {
            "status": "implemented",
            "proposal_id": pid,
            "asset_id": asset.asset_id,
            "decision_id": decision.decision_id,
            "immune_alert": immune_msg if immune_level != ImmuneLevel.NONE else "",
        }

    def accept_community_arbitration(self, conflict: dict) -> dict:
        """接受社区仲裁结论，触发免疫检测

        仲裁结论表明两个 H 之间价值观冲突已解决，
        此事件本身应被纳入免疫系统的行为基线。
        """
        cid = conflict.get("conflict_id", "")
        resolution = conflict.get("resolution", "")
        arbiter = conflict.get("arbiter_h_id", "")

        # 触发免疫——仲裁意味着群体中存在显著分歧
        self.immune.record_dismissal(arbiter or "_community")

        # 写入决策日志
        decision = Decision(
            h_id=arbiter or "_community",
            level="green",
            action="approved",
            description=f"社区仲裁: {resolution[:80]}",
            access_level="public",
        )
        self.d.save_decision(decision)

        # 溯源
        self.d.append_trace_log(cid, "arbitration_completed", f"resolved_by={arbiter}")

        return {
            "status": "logged",
            "conflict_id": cid,
            "decision_id": decision.decision_id,
        }

    def _restore_sessions(self):
        """V7.0：从 SQLite 恢复持久化的 sessions（未过期的才恢复）"""
        now = datetime.now()
        for s in self.d.load_sessions():
            if now < s["expires_at"]:
                h = H(h_id=s["h_id"], name=s["name"])
                self._h_sessions[s["token"]] = {
                    "h": h,
                    "created_at": s["created_at"],
                    "expires_at": s["expires_at"],
                    "last_used": s["last_used"],
                }

    def register_h(self, h_id: str, name: str = "") -> str:
        """注册 H——V6#4 修复：token 含 7 天过期时间"""
        token = secrets.token_hex(32)
        session_data = {
            "h": H(h_id=h_id, name=name or h_id),
            "created_at": datetime.now(),
            "last_used": datetime.now(),
            "expires_at": datetime.now() + timedelta(days=7),
        }
        self._h_sessions[token] = session_data
        # 持久化到 SQLite
        self.d.save_session(
            token,
            h_id,
            name or h_id,
            session_data["created_at"],
            session_data["expires_at"],
            session_data["last_used"],
        )
        # V6#7 惰性创建：首次注册后才 init community
        # B-01 修复：传入回调，社区提案通过后自动走 gate/immune 管道
        if self._community is None:
            from metaos.layers.community import CommunityEngine  # type: ignore[import-not-found]

            self._community = CommunityEngine(
                on_proposal_approved=self.accept_community_proposal,
                on_conflict_resolved=self.accept_community_arbitration,
            )
        self._community.register_h(h_id, "member")
        return token

    def authenticate(self, token: str) -> bool:
        """V6#4 修复：验证 token 有效期"""
        session = self._h_sessions.get(token)
        if not session:
            return False
        if datetime.now() > session["expires_at"]:
            self._h_sessions.pop(token, None)  # 过期自动清理
            return False
        h = session["h"]
        self._current_h_id = h.h_id
        session["last_used"] = datetime.now()
        return True

    def logout(self, token: str) -> bool:
        """V6#4 修复：主动登出"""
        return bool(self._h_sessions.pop(token, None))

    def clean_expired_tokens(self):
        """清理过期 token"""
        now = datetime.now()
        expired = [t for t, s in self._h_sessions.items() if now > s["expires_at"]]
        for t in expired:
            self._h_sessions.pop(t, None)
        return len(expired)

    @property
    def community(self):
        """V6#7 惰性访问——B-01 修复：传入回调"""
        if self._community is None:
            from metaos.layers.community import CommunityEngine

            self._community = CommunityEngine(
                on_proposal_approved=self.accept_community_proposal,
                on_conflict_resolved=self.accept_community_arbitration,
            )
        return self._community

    def assert_auth(self):
        """V-001 修复：仅在有注册 H 时要求认证"""
        if self._h_sessions and not self._current_h_id:
            raise PermissionError("V-001: 未认证的调用。使用 authenticate(token) 先认证")

    # ── 六步标准路径（V-004/V-007 修复：异常保护）──

    def process(self, task: Task, access_level: str = "public") -> dict:
        """处理一个任务。V5#2：access_level 默认为 public（群体场景可共享）"""
        self.assert_auth()
        task.h_id = self._current_h_id
        start_time = time.time()

        try:
            # Step 1: 权限判定
            try:
                level, reason, deadline = self.gate.evaluate(task)
            except Exception as e:  # defensive fallback  # noqa: BLE001
                return self._safely_fail(task, "gate_error", str(e))

            if level == DecisionLevel.RED:
                return {
                    "status": "pending_h",
                    "task_id": task.task_id,
                    "level": "red",
                    "h_id": self._current_h_id,
                    "message": f"🔴 红灯决策: {reason}。等待 H 实时确认。",
                }

            # Step 2: 路由决策
            try:
                healthy = self.m.get_healthy_models()
                model_ids = self.router.resolve(task, healthy)
                if not model_ids:
                    return {
                        "status": "failed",
                        "task_id": task.task_id,
                        "h_id": self._current_h_id,
                        "message": "无可用模型（M 全量不可用，建议切换离线模式）",
                    }
            except Exception as e:  # defensive fallback  # noqa: BLE001
                return self._safely_fail(task, "router_error", str(e))

            # P1：附加上下文——最近原则
            try:
                history = self.d.get_principles(status="active")[:3]
                if history:
                    ctx = "\n".join([f"- {p.content[:80]}" for p in history])
                    task.input += f"\n\n【已有原则参考】\n{ctx}"
            except Exception:  # defensive fallback  # noqa: BLE001
                pass

            # Step 3: M 执行
            try:
                result = self.m.call(task, model_ids[0])
            except Exception as e:  # defensive fallback  # noqa: BLE001
                return self._safely_fail(task, "m_error", str(e))

            # Step 4: 免疫检测
            try:
                recent = self.d.get_decisions(self._current_h_id, 10)
                principles = self.d.get_principles()
                immune_level, immune_msg = self.immune.evaluate(self._current_h_id, task.input, recent, principles)
            except Exception:  # defensive fallback  # noqa: BLE001
                immune_level, immune_msg = ImmuneLevel.NONE, ""

            # Step 5: V-008 修复 —— 待确认决策同步写 DB
            decision = Decision(
                h_id=self._current_h_id,
                level=level.value,
                description=task.input[:100],
                assets_used=[result.task_id],
                immune_triggered=immune_level.value,
                outcome_pending_review=(level == DecisionLevel.YELLOW),
                review_deadline=deadline,
                access_level=access_level,  # V5#2 修复
            )

            # 先写 DB（异常安全）
            self.d.save_decision(decision)

            if level == DecisionLevel.YELLOW:
                self._pending_yellow.append(decision)
                msg = f"🟡 黄灯区: {reason}。执行完毕，请在 {deadline.strftime('%m-%d %H:%M')} 前确认。"
            else:
                msg = "🟢 绿灯区: 自动执行完毕。"

            if immune_level != ImmuneLevel.NONE:
                msg += f"\n{immune_msg}"

            # Step 6: 溯源日志
            try:
                self.d.append_trace_log(task.task_id, "completed", f"gate={level.value} immune={immune_level.value}")
            except Exception:  # defensive fallback  # noqa: BLE001
                pass  # 溯源日志失败不影响主流程

            return {
                "status": "completed",
                "task_id": task.task_id,
                "level": level.value,
                "h_id": self._current_h_id,
                "output": result.output,
                "confidence": result.confidence,
                "immune_alert": immune_msg if immune_level != ImmuneLevel.NONE else "",
                "message": msg,
                "latency_ms": int((time.time() - start_time) * 1000),
            }

        except Exception:  # defensive fallback  # noqa: BLE001
            return self._safely_fail(task, "unexpected", traceback.format_exc())

    def _safely_fail(self, task: Task, stage: str, detail: str) -> dict:
        """V4#9 修复：安全降级 + logging 告警 + 异常统计"""
        logger.error("ENGINE_FAIL stage=%s task=%s detail=%.200s", stage, task.task_id, detail)
        self._error_log.append(f"[{datetime.now().strftime('%m-%d %H:%M')}] {stage}: {detail[:80]}")
        if len(self._error_log) > 50:
            self._error_log.pop(0)
        try:
            self.d.append_trace_log(task.task_id, f"failed:{stage}", detail[:200])
        except Exception:  # defensive fallback  # noqa: BLE001
            pass
        return {
            "status": "failed",
            "task_id": task.task_id,
            "h_id": self._current_h_id,
            "stage": stage,
            "message": f"步骤 {stage} 异常，已安全降级: {detail[:100]}",
        }

    # ── H 确认操作（V-010 修复：显式 quality 格式）──

    def h_confirm(self, decision_id: str, action: str, comment: str = "") -> dict:
        """
        H 确认决策。V-010 修复：quality 使用显式标记 `quality:N`
        示例: "accept,quality:8" 或 "reject,reason:not relevant"
        """
        self.assert_auth()
        decision = None
        for d in self._pending_yellow:
            if d.decision_id == decision_id:
                decision = d
                break

        if not decision:
            return {"status": "error", "message": f"决策 {decision_id} 未找到"}

        # V5#5 修复：验证决策归属
        if decision.h_id != self._current_h_id:
            return {"status": "error", "message": f"决策 {decision_id} 不属于当前 H ({self._current_h_id})"}

        decision.action = action
        decision.outcome_pending_review = False

        # TD-01 修复：先写 DB，成功后再移除 pending
        try:
            self.d.save_decision(decision)
        except Exception as e:  # defensive fallback  # noqa: BLE001
            return {"status": "error", "message": f"决策确认失败（DB 写入错误）: {e}"}

        if action == "rejected":
            self.d.append_trace_log(decision_id, "h_confirm:rejected", comment)
            self._pending_yellow = [d for d in self._pending_yellow if d.decision_id != decision_id]
            return {"status": "ok", "message": f"决策 {decision_id} 已驳回"}

        # V4#5 修复：quality 使用独立方法记录，不从 comment 提取
        quality_msg = "（结果质量请用 record_quality() 单独记录）"

        self.d.append_trace_log(decision_id, "h_confirm:approved", comment)
        self._pending_yellow = [d for d in self._pending_yellow if d.decision_id != decision_id]

        return {
            "status": "ok",
            "message": f"决策 {decision_id} 已确认",
            "note": quality_msg,
        }

    def check_pending_reviews(self) -> list[dict]:
        self.assert_auth()
        overdue = []
        now = datetime.now()
        remaining = []
        for d in self._pending_yellow:
            if d.review_deadline and now > d.review_deadline:
                overdue.append(
                    {
                        "decision_id": d.decision_id,
                        "description": d.description,
                        "deadline": d.review_deadline.isoformat(),
                        "action": "auto_frozen",
                    }
                )
                self.immune.record_timeout(self._current_h_id)  # V5#7 修复：独立超时计数
            else:
                remaining.append(d)
        self._pending_yellow = remaining
        return overdue

    def metacognitive_check(self, question: str, h_answer: str) -> dict:
        self.assert_auth()
        self.d.append_trace_log("metacognition", f"Q: {question}", f"A: {h_answer}")
        return {"status": "recorded", "question": question, "answer": h_answer}

    def generate_metacognitive_report(self) -> dict:
        self.assert_auth()
        recent = self.d.get_decisions(self._current_h_id, 20)
        report = self.immune.metacognitive_quality_report(self._current_h_id, recent, [])
        self.d.append_trace_log("meta_report", report.get("diagnosis", "no diagnosis"), str(report))
        return report

    def record_quality(self, decision_id: str, quality: float) -> dict:
        """
        V4#5 修复：quality 独立记录方法，与 h_confirm 分离。
        quality 0.0-1.0，由微粒复盘环节产生。
        """
        self.assert_auth()
        triggered = self.immune.record_acceptance_outcome(self._current_h_id, decision_id, "decision", quality)
        self.d.append_trace_log(decision_id, f"quality:{quality:.1f}", "")
        return {"status": "ok", "triggered_alert": triggered}

    def record_acceptance_outcome(self, decision_id: str, recommendation: str, outcome_quality: float):
        self.assert_auth()
        return self.immune.record_acceptance_outcome(self._current_h_id, decision_id, recommendation, outcome_quality)

    def system_health(self) -> dict:
        """V4#9 修复：暴露最近异常——V7.0 修复：暴露后端信息"""
        healthy_models = self.m.get_healthy_models()
        total_models = len(self.m.models)
        return {
            "m_pool": f"{len(healthy_models)}/{total_models} healthy",
            "d_layer": "ok",
            "pending_reviews": len(self._pending_yellow),
            "frozen": list(self.immune._frozen),
            "meltdown": list(self.immune._meltdown),
            "offline_mode": self._offline_mode,
            "auth_enabled": bool(self._h_sessions),
            "recent_errors": list(self._error_log[-5:]),
            "backend": self.m.backend_name,
        }

    # ── 向后兼容属性 ──
    @property
    def current_h(self) -> H:
        """兼容旧代码：返回当前 H 的信息"""
        h_id = self._current_h_id or "_anonymous"
        return H(h_id=h_id)

    def check_transition_to_offline(self) -> bool:
        healthy = len(self.m.get_healthy_models())
        total = len(self.m.models)
        if self._offline_mode:
            if healthy == total:
                self._health_pass_count += 1
                if self._health_pass_count >= self._stable_window_exit:
                    self._offline_mode = False
                    self._health_pass_count = 0
                    self._health_fail_count = 0
                    return False
            else:
                self._health_pass_count = 0
            return True
        if healthy == 0:
            self._health_fail_count += 1
            if self._health_fail_count >= self._stable_window_enter:
                self._offline_mode = True
                self._health_fail_count = 0
                return True
        else:
            self._health_fail_count = 0
        return False
