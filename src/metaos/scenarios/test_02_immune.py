"""场景02：免疫机制测试——提醒→冻结→熔断"""



from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import Decision, Task  # type: ignore[import-not-found]


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_s02_")
    print("=" * 60)
    print("  场景02：免疫机制——从提醒→冻结→熔断的完整路径")
    print("=" * 60)

    engine = SEngine(data_dir=data_dir)

    # ── 测试第一层：模式异常检测 ──
    print("\n[测试1] 制造驳回率异常")
    # 直接写入带 rejected 的决策（跳过 h_confirm 的队列限制）
    for i in range(8):
        d = Decision(
            h_id="H_001",
            level="green",
            action="rejected" if i % 2 == 0 else "approved",
            description=f"mock_decision_{i}",
            outcome_pending_review=False,
        )
        engine.d.save_decision(d)

    # 触发异常检测
    recent = engine.d.get_decisions("H_001", 10)
    anomaly, msg = engine.immune.check_pattern_anomaly("H_001", recent)
    print(f"  模式异常检测: {'✅ 触发' if anomaly else '❌ 未触发'}")
    print(f"  消息: {msg}")
    assert anomaly, "驳回率异常未检测到"

    # ── 测试第二层：累计驳回→冻结 ──
    print("\n[测试2] 累计驳回触发冻结")
    engine.immune._dismissal_count["H_001"] = 0  # 重置
    for i in range(3):
        engine.immune.record_dismissal("H_001")
    frozen = engine.immune.is_frozen("H_001")
    print(f"  冻结状态: {'✅ 已冻结' if frozen else '❌ 未冻结'}")
    assert frozen, "3次驳回后应冻结"

    # 冻结后处理任务
    task = Task(h_id="H_001", task_type="reasoning", input="推荐一个方案")
    r = engine.process(task)
    print(f"  冻结后任务级别: {r['level']}")
    # 冻结后仍可执行，但免疫会提示

    # ── 测试第三层：触发熔断 ──
    print("\n[测试3] 触发熔断")
    engine.immune.trigger_meltdown("H_001")
    meltdown = engine.immune.is_meltdown("H_001")
    print(f"  熔断状态: {'✅ 已熔断' if meltdown else '❌ 未熔断'}")
    assert meltdown, "熔断应被触发"

    task2 = Task(h_id="H_001", task_type="reasoning", input="这项投资是否值得")
    r2 = engine.process(task2)
    print(f"  熔断后任务状态: {r2['status']}")
    # 熔断后系统仍可响应

    # ── 释放熔断 ──
    print("\n[测试4] 释放熔断")
    engine.immune.release_meltdown("H_001")
    engine.immune.release_freeze("H_001")
    print(f"  熔断: {'已释放' if not engine.immune.is_meltdown('H_001') else '异常'}")
    print(f"  冻结: {'已释放' if not engine.immune.is_frozen('H_001') else '异常'}")

    print("\n✅ 场景02验证通过——三层免疫路径全部跑通")
    return engine


if __name__ == "__main__":
    run_scenario()
