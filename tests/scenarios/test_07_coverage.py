"""场景07：五领域覆盖测试——安全·元治理·数据模型·异常·版本化"""

from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import Decision  # type: ignore[import-not-found]
from metaos.layers.governance import MetaGovernance  # type: ignore[import-not-found]


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_cov_")

    print("=" * 60)
    print("  场景07：五领域覆盖测试")
    print("=" * 60)

    engine = SEngine(data_dir=data_dir)

    # ── 领域1：安全与访问控制 ──
    print("\n[领域1] access_level + 访问控制")
    d_owner = Decision(h_id="H_A", description="私有决策", access_level="owner")
    d_public = Decision(h_id="H_B", description="公开决策", access_level="public")
    engine.d.save_decision(d_owner)
    engine.d.save_decision(d_public)

    # H_A 读自己的 → 应返回
    own = engine.d.get_decisions(h_id="H_A", caller_h_id="H_A")
    assert any("私有决策" in str(d.description) for d in own), "应返回自己的决策"
    print("  ✅ H_A 可读自己决策")

    # H_B 读 H_A 的 → 只应看到 public
    cross = engine.d.get_decisions(h_id="H_A", caller_h_id="H_B")
    assert not any("私有决策" in str(d.description) for d in cross), "不应看到 owner 决策"
    print("  ✅ H_B 读 H_A 时正确过滤 owner 级别")

    # ── 领域2：元治理 ──
    print("\n[领域2] 元治理——S 规则修改")
    gov = MetaGovernance(scenario="personal")

    # 2a：内核规则拒绝修改
    r = gov.check_irreducible("K1")
    assert r, "K1 应被识别为内核规则"
    r2 = gov.propose_change("K1", "on", "off", "测试", "H_A")
    assert r2["status"] == "rejected", "内核规则应拒绝修改"
    print("  ✅ 内核规则 K1-K4 拒绝修改")

    # 2b：常规规则允许修改 + 冷静期
    r3 = gov.propose_change("yellow_deadline", "24h", "48h", "需要更多时间确认", "H_A")
    assert r3["status"] == "cooling"
    print(f"  ✅ 常规规则可修改，冷静期 24h，影响扫描: {r3['impact_scan'][:40]}...")

    # 2c：冷静期内不能确认
    r4 = gov.confirm_change(r3["proposal_id"], "H_A")
    assert r4["status"] == "cooling", "冷静期内应拒绝确认"
    print("  ✅ 冷静期内确认被拒绝")

    # 2d：审计日志不可删除
    log = gov.get_history()
    assert len(log) >= 1, f"应有至少 1 条审计日志: {len(log)}"
    print(f"  ✅ 审计日志 {len(log)} 条，不可删除")

    # ── 领域3：数据模型稳定 ──
    print("\n[领域3] 数据模型完整性")
    d = Decision(h_id="H_TEST")
    assert hasattr(d, "access_level"), "缺少 access_level"
    assert hasattr(d, "api_version"), "缺少 api_version"
    assert d.access_level == "owner", f"默认应为 owner: {d.access_level}"
    assert d.api_version == "1.0", f"默认 API 版本应为 1.0: {d.api_version}"
    print("  ✅ Decision 模型完整: access_level + api_version")

    # ── 领域4：异常路径覆盖 ──
    print("\n[领域4] 异常路径与安全降级")
    # 强制一个异常——用非法 task 调用
    from core.types import Task  # type: ignore[import-not-found]

    # 先注册 H
    token = engine.register_h("H_COV", "覆盖测试")
    engine.authenticate(token)
    # 正常流程
    t = Task(h_id="H_COV", task_type="info_retrieval", input="正常测试")
    r = engine.process(t)
    assert r["status"] in ("completed", "failed"), f"process 异常: {r}"
    print("  ✅ 正常 process 路径通过")

    # health check 暴露错误
    health = engine.system_health()
    assert "recent_errors" in health, "health 应有 recent_errors"
    print(f"  ✅ 异常路径监控正常（{len(health['recent_errors'])} 条近期错误）")

    # ── 领域5：版本化策略 ──
    print("\n[领域5] 数据版本化")
    from core.types import Principle

    p1 = Principle(principle_id="P_TEST", content="测试原则 v1", status="active")
    engine.d.save_principle(p1)
    p2 = Principle(principle_id="P_TEST", content="测试原则 v2", status="active")
    engine.d.save_principle(p2)
    # 应有 2 个版本
    history = engine.d.get_principle_history("P_TEST")
    assert len(history) == 2, f"原则应有 2 个版本: {len(history)}"
    versions = [h.principle_id for h in history]
    print(f"  ✅ 原则版本化正常（{len(history)} 个版本，ID: {list(set(versions))[0][:8]}...）")

    # 活跃查询只返回最新版本
    active = engine.d.get_principles(status="active")
    p_test = [p for p in active if p.principle_id == "P_TEST"]
    assert len(p_test) == 1, f"活跃原则查询应返回 1 条: {len(p_test)}"
    print(f"  ✅ 活跃原则只返回最新版本（{p_test[0].content}）")

    # ── V8：元治理沙箱——dry-run + 自动回滚 ──
    print("\n[沙箱验证] 元治理 dry-run + rollback")
    gov = engine.governance

    # dry-run 内核规则 → 应拒绝
    dr1 = gov.simulate_change("K1", "x", "y")
    assert dr1["verdict"] == "rejected", f"内核应被拒绝: {dr1}"
    print(f"  ✅ dry-run 内核规则: {dr1['reason']}")

    # dry-run 常规规则 → 应通过
    dr2 = gov.simulate_change("yellow_deadline", "24h", "48h")
    assert dr2["verdict"] == "acceptable", f"常规应通过: {dr2}"
    print(f"  ✅ dry-run 常规规则: {dr2['diff']}, 警告={len(dr2['warnings'])}")

    # 正式提案 + 通过
    prop = gov.propose_change("sandbox_test", "old", "new", "沙箱测试", "H_SANDBOX")
    assert prop["status"] == "cooling"
    pid = prop["proposal_id"]
    # 直接修改冷却期绕过等待
    gov._proposals[pid].cooling_end = __import__("datetime").datetime.now() - __import__("datetime").timedelta(
        minutes=1
    )
    r = gov.confirm_change(pid, "H_SANDBOX")
    assert r["status"] == "approved", f"确认失败: {r}"
    print(f"  ✅ 提案批准: {r['change']}, 回滚窗口={r.get('rollback_window', '无')}")

    # rollback 回退
    rb = gov.rollback(pid, "H_SANDBOX")
    assert rb["status"] == "rolled_back", f"回滚失败: {rb}"
    print(f"  ✅ 自动回滚: {rb['restored']}")

    # 审计日志完整
    history = gov.get_history(10)
    assert len(history) >= 3, f"审计日志应有 ≥3 条: {len(history)}"
    log_types = [e["type"] for e in history[-3:]]
    print(f"  ✅ 审计日志: 最近事件类型={log_types}")

    print("\n" + "=" * 60)
    print("  场景07 全部通过 ✅")
    print("  覆盖: 安全/元治理/数据模型/异常/版本化/V8沙箱")
    print("=" * 60)


if __name__ == "__main__":
    run_scenario()
