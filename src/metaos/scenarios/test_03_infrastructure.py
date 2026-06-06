"""场景03：基础设施故障——M 全量宕机 + 离线恢复"""



from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import Task  # type: ignore[import-not-found]


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_s03_")
    print("=" * 60)
    print("  场景03：系统崩溃——M 全量不可用 + 恢复")
    print("=" * 60)

    engine = SEngine(data_dir=data_dir)

    # ── 正常状态 ──
    print("\n[正常状态] M 可用")
    health = engine.system_health()
    print(f"  M 池: {health['m_pool']}")
    assert "0/" not in health["m_pool"], "开始时 M 应可用"

    # ── 注入故障 ──
    print("\n[故障注入] 全部模型宕机")
    engine.m.inject_failure(["general", "reasoning", "code", "domain"])
    health = engine.system_health()
    print(f"  M 池: {health['m_pool']}")
    assert "0/" in health["m_pool"], "M 应全部不可用"

    # ── 尝试处理任务 ──
    print("\n[离线模式] H 尝试晨间仪式")
    task = Task(h_id="H_001", task_type="morning_ritual", input="晨间启动")
    r = engine.process(task)
    print(f"  结果: {'✅ 正确降级' if '不可用' in r.get('message', '') else '❌ 异常'}")
    print(f"  消息: {r.get('message', '')}")
    assert "不可用" in r.get("message", ""), "M 不可用时应有提示"

    # ── 使用离线日记模板 ──
    print("\n[离线模式] H 使用手动日记模板")
    print("""
【离线日记模板】
今日核心任务（完成/部分/未完成）：
1. 合同审阅 → 完成
2. 演示文稿 → 部分

今日关键决策及依据：
决策1：拒绝对方赔偿上限80%条款 → 依据经验教训

提取一条教训：
离线模式下决策更保守但也更独立
""")

    # ── 恢复 ──
    print("\n[M 恢复] 模型重建")
    engine.m.restore_all()
    health = engine.system_health()
    print(f"  M 池: {health['m_pool']}")

    # ── 恢复后处理 ──
    print("\n[恢复后] 执行补处理")
    task2 = Task(h_id="H_001", task_type="micro_review", input="复盘今天：M不可用时的应对")
    r2 = engine.process(task2)
    assert r2["status"] == "completed", "恢复后处理失败"
    print(f"  复盘结果: {r2['output'][:80]}...")

    print("\n✅ 场景03验证通过——基础设施故障→离线→恢复全链路")
    return engine


if __name__ == "__main__":
    run_scenario()
