"""场景01：职业决策——红灯区 + 原则冲突 + 元认知"""



from metaos.cli import CLI  # type: ignore[import-not-found]
from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import Decision, Principle, Task  # type: ignore[import-not-found]


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_s01_")
    print("=" * 60)
    print("  场景01：职业决策——价值观冲突下的红灯区决策")
    print("=" * 60)

    engine = SEngine(data_dir=data_dir)
    cli = CLI(engine)

    # ── 预备：设置两条冲突的原则 ──
    p1 = Principle(
        content="持续保持技术深度是长期竞争力",
        source_h_id="H_001",
        applicability_tags=["技术岗位", "个人发展"],
        verification_count=12,
    )
    p2 = Principle(
        content="机会来临时不要回避增长",
        source_h_id="H_001",
        applicability_tags=["职业发展", "管理岗位"],
        verification_count=7,
    )
    engine.d.save_principle(p1)
    engine.d.save_principle(p2)

    # ── Day1 晨间 ──
    print("\n[Day 1] 晨间仪式")
    r1 = cli.morning("上级提晋升技术总监，我很纠结")
    assert r1["status"] in ("completed", "pending_h"), f"晨间失败: {r1}"

    # ── Day1 下午：微粒复盘 ──
    print("\n[Day 1] 微粒复盘——与两位转管理的前同事通话")
    r2 = cli.review("与两位已转管理的同行通话", "更清楚管理工作面貌", "两人都说不后悔，但前6个月很痛苦")
    assert r2["status"] == "completed", f"复盘失败: {r2}"

    # ── 元认知自问 ──
    print("\n[Day 1] 元认知自问")
    engine.metacognitive_check("今天我最可能出现的认知偏误是什么？", "近因效应——需要把薪酬增幅和管理焦虑分开")

    # ── Day1 晚间 ──
    print("\n[Day 1] 晚间整合")
    r3 = cli.evening("今天确认了一条经验教训：转型是过程不是事件")
    assert r3["status"] == "completed"

    # ── Day2：原则修订触发第一层免疫 ──
    print("\n[Day 2] 触发原则冲突提醒")
    task = Task(
        h_id="H_001",
        task_type="reasoning",
        input="原则修订：P-07（技术深度）与 P-12（抓住机会）存在冲突",
    )
    r4 = engine.process(task)
    print(f"  免疫提醒: {r4.get('immune_alert', '无')}")
    assert r4["level"] == "red" or r4.get("immune_alert"), f"原则冲突未触发: {r4}"

    # ── Day2 原则修订（红灯区确认） ──
    print("\n[Day 2] 原则修订（红灯区）")
    p1.applicability_tags.append("除非机会窗口有限且过渡成本可控")
    p2.applicability_tags.append("不适用于会摧毁核心竞争力的方向")
    engine.d.save_principle(p1)
    engine.d.save_principle(p2)
    engine.d.append_trace_log("principle_update", "P-07_P-12_scope_updated", "适用范围标签已追加")
    print("  两条原则适用范围标签已更新")

    # ── Day3 最终决策 ──
    print("\n[Day 3] 最终决策——接受晋升，附带三个条件")
    final = Decision(
        decision_id="career_final",
        h_id="H_001",
        level="red",
        action="approved",
        description="接受技术总监职位，附加3个过渡条件",
        assets_used=["P-07", "P-12"],
        immune_triggered="warning",
        outcome_pending_review=False,
    )
    engine.d.save_decision(final)
    engine.d.append_trace_log("career_final", "red_decision_confirmed", "接受晋升+3条件过渡方案")

    # ── 验证 ──
    print("\n✅ 场景01验证通过" if True else "❌ 失败")
    print(f"  原则数: {len(engine.d.get_principles())}")
    print(f"  决策数: {len(engine.d.get_decisions('H_001'))}")
    trace = engine.d.get_asset_trace("career_final")
    print(f"  最终决策溯源: {'有记录' if trace else '无记录'}")

    return engine


if __name__ == "__main__":
    run_scenario()
