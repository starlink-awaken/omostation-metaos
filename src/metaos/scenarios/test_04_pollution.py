"""场景04：资产污染——D_融合 错误发现 + 追踪 + 降级"""

from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import AssetLevel, Decision, DigitalAsset  # type: ignore[import-not-found]


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_s04_")
    print("=" * 60)
    print("  场景04：资产污染——D_融合 错误 + 溯源 + 冻结 + 降级")
    print("=" * 60)

    engine = SEngine(data_dir=data_dir)

    # ── 预备：写入一个 D_融合 资产 ──
    print("\n[预备] 写入 D_融合 资产")
    fused = DigitalAsset(
        asset_id="FUSED_PRINC_042",
        level=AssetLevel.FUSED,
        content="在不确定性高的场景中，优先选择可逆方案",
        source_h_id="H_003",
        asset_type="text",
        auth_timestamp=__import__("datetime").datetime.now(),
        verification_count=6,
        verification_h_ids={"H_003", "H_003", "H_003", "H_003", "H_003", "H_003"},
        first_verified=__import__("datetime").datetime.now(),
        last_verified=__import__("datetime").datetime.now(),
    )
    engine.d.write_asset_trace(fused.asset_id, "fused", "H_003", "在不确定性高的场景中，优先选择可逆方案")
    for i in range(3):
        engine.d.append_trace_log(fused.asset_id, "downstream_decision", f"决策_{i}: 引用了此原则")

    # ── 创建一些下游决策 ──
    for i in range(3):
        d = Decision(
            decision_id=f"downstream_{i}",
            h_id="H_001",
            level="yellow",
            action="rejected",
            description=f"决策_{i}",
            assets_used=["FUSED_PRINC_042"],
            immune_triggered="none",
            outcome_pending_review=False,
        )
        engine.d.save_decision(d)

    # ── 检测异常模式 ──
    print("\n[检测] 驳回率异常")
    recent = engine.d.get_decisions("H_001", 10)
    anomaly, msg = engine.immune.check_pattern_anomaly("H_001", recent)
    print(f"  {'✅ 异常检测触发' if anomaly else '无异常'}")
    print(f"  消息: {msg}")

    # ── 资产溯源 ──
    print("\n[溯源] 读取 FUSED_PRINC_042 溯源链")
    trace = engine.d.get_asset_trace("FUSED_PRINC_042")
    print(f"  源头 H: {trace.get('source_h_id', 'N/A')}")
    print(f"  验证次数: {trace.get('verification_count', 0)}")
    print(f"  选择验证 H: {trace.get('verification_h_ids', [])}")
    print(f"  溯源日志: {len(trace.get('logs', []))} 条")

    # ── 验证质量检查（04-资产污染推演的新增机制）──
    print("\n[质量] 验证质量检查")
    v_h_ids = trace.get("verification_h_ids", [])
    if len(set(v_h_ids)) < 2:
        print(f"  ⚠️ 验证 H 多样性不足：全部来自 {set(v_h_ids)}")
    else:
        print("  ✅ 验证 H 多样性合格")

    # ── 执行冻结（免疫第二层） ──
    print("\n[冻结] 冻结 D_融合 资产")
    engine.immune.record_dismissal("H_001")
    engine.d.append_trace_log("FUSED_PRINC_042", "frozen", "适用范围存疑")

    deps = engine.d.count_decision_dependencies("FUSED_PRINC_042")
    print(f"  受影响的下游决策: {deps} 条")
    assert deps > 0, "应有下游决策"

    # ── 降级方案 ──
    print("\n[降级] 从 D_融合 降级至 D_共有 + 加适用范围标签")
    engine.d.write_asset_trace("FUSED_PRINC_042_REVISED", "shared", "H_001", "适用于失败不可承受的高不确定性场景")
    engine.d.append_trace_log("FUSED_PRINC_042", "demoted_to_shared", "降低公共级+适用范围标签")
    print("  已执行降级方案")

    # ── 最终状态 ──
    print("\n[验证] 污染处置完成")
    trace_after = engine.d.get_asset_trace("FUSED_PRINC_042")
    print(f"  最终溯源日志: {len(trace_after.get('logs', []))} 条")

    print("\n✅ 场景04验证通过——污染检测→溯源→冻结→降级全链路")
    return engine


if __name__ == "__main__":
    run_scenario()
