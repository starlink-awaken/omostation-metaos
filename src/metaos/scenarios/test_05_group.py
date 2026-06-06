"""群体场景推演：3 个 H 的架构选型冲突
覆盖：多 H 注册·D_共有 提案·价值冲突登记·委员会仲裁·涌现条件检查
"""



from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.layers.community import (  # type: ignore[import-not-found]
    CommunityEngine,
    ConflictStatus,
    ProposalStatus,
    VoteType,
)


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_group_")

    print("=" * 60)
    print("  群体场景推演：3 H 架构选型冲突")
    print("=" * 60)

    community = CommunityEngine()
    engine = SEngine(data_dir=data_dir)

    # ── 第 1 步：注册 3 个 H ──
    print("\n[Step 1] 注册委员会")
    r1 = community.register_h("H_A", "member")
    r2 = community.register_h("H_B", "member")
    r3 = community.register_h("H_C", "chair")
    assert r1["status"] == "ok" and r2["status"] == "ok" and r3["status"] == "ok"
    print(f"  已注册: {[m['h_id'] for m in community.list_members()]}")

    # ── 第 2 步：涌现条件检查（应未达标）──
    print("\n[Step 2] 涌现条件检查（初期）")
    emergence = community.check_emergence_conditions()
    assert not emergence["emergence_detected"], "初期不应涌现"
    print(f"  已达标: {emergence['met_count']}/{emergence['total_conditions']}")
    print("  预期: 未涌现 (正确)")

    # ── 第 3 步：H_A 提出 D_共有 提案──
    print("\n[Step 3] H_A 提案：微服务架构")
    prop = community.propose_shared_asset(
        "H_A",
        "采纳微服务架构",
        "新模块采用微服务，独立部署，提高团队自治性",
        vote_hours=72,
    )
    assert prop.status == ProposalStatus.PENDING
    print(f"  提案 ID: {prop.proposal_id[:12]}")
    print(f"  状态: {prop.status.value}")

    # ── 第 4 步：投票 ──
    print("\n[Step 4] 投票")
    r = community.vote_on_proposal(prop.proposal_id, "H_A", VoteType.APPROVE)
    assert r["status"] == "ok"
    r = community.vote_on_proposal(prop.proposal_id, "H_B", VoteType.REJECT)
    assert r["status"] == "ok"
    r = community.vote_on_proposal(prop.proposal_id, "H_C", VoteType.APPROVE)
    assert r["status"] == "ok"
    print(f"  结果: for={r['for']} against={r['against']} → {r['state']}")
    assert r["state"] == "approved", "应通过 (3H, 60%阈值=2票)"
    print("  ✅ 提案通过")

    # ── 第 5 步：价值冲突登记 ──
    print("\n[Step 5] 价值冲突登记")
    conflict = community.register_conflict(
        asset_id="P_S-03",
        h_a="H_A",
        h_b="H_B",
        pos_a="微服务符合团队长期成长需求",
        pos_b="微服务超出团队当前运维能力",
    )
    assert conflict.status == ConflictStatus.OPEN
    print(f"  冲突 ID: {conflict.conflict_id[:12]}")
    print(f"  仲裁者: {conflict.arbiter_h_id}")
    assert conflict.arbiter_h_id == "H_C", "主席应为仲裁者"

    # ── 第 6 步：仲裁 ──
    print("\n[Step 6] 委员会仲裁")
    resolution = (
        "双方立场均合理。折中方案：新模块使用微服务架构，但设置 3 个月回退检查点。首月由 H_B 负责监控体系搭建。"
    )
    r = community.resolve_conflict(conflict.conflict_id, resolution)
    assert r["status"] == "ok"
    print(f"  仲裁结果: {resolution[:50]}...")
    assert community._conflicts[conflict.conflict_id].status == ConflictStatus.RESOLVED
    print("  ✅ 冲突已解决")

    # ── 第 7 步：涌现条件再检查（更多提案构建 D_共有）──
    print("\n[Step 7] 涌现条件检查（积累资产后）")
    # 模拟积累 D_共有 资产
    for i in range(8):
        p = community.propose_shared_asset(
            f"H_{['A', 'B', 'C'][i % 3]}",
            f"经验教训_{i}",
            f"来自 H_{['A', 'B', 'C'][i % 3]} 的第 {i} 条经验",
        )
        for h in ["H_A", "H_B", "H_C"]:
            community.vote_on_proposal(p.proposal_id, h, VoteType.APPROVE)

    emergence2 = community.check_emergence_conditions(d_shared_count=9)
    print(f"  已达标: {emergence2['met_count']}/{emergence2['total_conditions']}")
    print(f"  详情: {emergence2['details']}")
    for cond, info in emergence2["details"].items():
        status = "✅" if info["met"] else "❌"
        print(f"    {status} {cond}: {info['value']}/{info['threshold']}")

    # ── 第 8 步：委员会轮值 ──
    print("\n[Step 8] 委员会轮值")
    r = community.rotate_chair()
    assert r["status"] == "ok"
    print(f"  新主席: {r['new_chair']}")
    members = community.list_members()
    for m in members:
        print(f"    {m['h_id']}: {m['role']}")

    # ── 第 9 步：过半数提案 + 大量冲突 → 涌现条件部分达标 ──
    print("\n[Step 9] 涌现条件检测（模拟达标临界）")
    # 模拟更多冲突和仲裁以达到涌现门槛
    for i in range(3):
        c = community.register_conflict(f"asset_conflict_{i}", "H_A", "H_B", f"立场_A_{i}", f"立场_B_{i}")
        community.resolve_conflict(c.conflict_id, f"仲裁_{i}")

    emergence3 = community.check_emergence_conditions(d_shared_count=51)
    print(f"  已达标: {emergence3['met_count']}/{emergence3['total_conditions']}")
    print(f"  涌现检测: {'✅ 已达到门槛' if emergence3['emergence_detected'] else '❌ 未达标'}")
    print(f"  注意事项: {emergence3['note']}")

    # ── V6#1：Community → SEngine 运行时通道 ──
    print("\n[Step 10] Community → SEngine 运行时通道")
    # 通过社区提案触发 SEngine 决策流
    approved = [p for p in community._proposals.values() if p.status == ProposalStatus.APPROVED]
    if approved:
        prop = approved[0]
        proposal_data = {
            "proposal_id": prop.proposal_id,
            "title": prop.title,
            "content": prop.content,
            "proposer_h": prop.proposer_h,
        }
        r = engine.accept_community_proposal(proposal_data)
        assert r["status"] == "implemented", f"提案应被实施: {r}"
        print(f"  ✅ 提案 {prop.proposal_id[:8]} 已处理→资产 {r['asset_id'][:8]} 决策 {r['decision_id'][:8]}")
        print(f"  免疫告警: {r.get('immune_alert') or '无'}")

    # 仲裁结论触发免疫
    resolved = [c for c in community._conflicts.values() if c.status == ConflictStatus.RESOLVED]
    if resolved:
        c = resolved[0]
        conflict_data = {
            "conflict_id": c.conflict_id,
            "resolution": c.resolution,
            "arbiter_h_id": c.arbiter_h_id,
        }
        r2 = engine.accept_community_arbitration(conflict_data)
        assert r2["status"] == "logged", f"仲裁应被记录: {r2}"
        print(f"  ✅ 仲裁 {c.conflict_id[:8]} 已写入决策日志")

    # 验证双引擎同步
    channel_ok = bool(approved) and bool(resolved)
    if approved:
        print("  ✅ 社区提案→SEngine 决策流：正常")
    if resolved:
        print("  ✅ 社区仲裁→SEngine 免疫检测：正常")
    if not channel_ok:
        print("  ⚠️  部分通道未测试（无提案或无冲突数据）")

    print("\n" + "=" * 60)
    print("  群体场景推演完成")
    print(f"  提案数量: {len(community._proposals)}")
    print(f"  冲突登记: {len(community._conflicts)}")
    print(f"  委员会: {len(community._committee)} 人")
    print(f"  涌现条件达标: {emergence3['met_count']}/{emergence3['total_conditions']}")
    print("  V6#1 通道: ✅ 提案+仲裁已接入 SEngine")
    print("=" * 60)


if __name__ == "__main__":
    run_scenario()
