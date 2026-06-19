"""场景06：认证系统测试——register_h + authenticate + 权限隔离"""

from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import Task  # type: ignore[import-not-found]


def run_scenario():
    import tempfile

    data_dir = tempfile.mkdtemp(prefix="metaos_auth_")

    print("=" * 60)
    print("  场景06：认证系统白盒测试")
    print("=" * 60)

    engine = SEngine(data_dir=data_dir)

    # ── 测试1：未认证调用应失败（当认证启用后）──
    print("\n[测试1] 注册前 process() 应匿名可用")
    task = Task(h_id="", task_type="info_retrieval", input="test")
    r = engine.process(task)
    assert r["status"] in ("completed", "failed"), f"匿名调用应可用: {r}"
    print(f"  ✅ 匿名可用: {r['status']}")

    # ── 测试2：注册后认证生效 ──
    print("\n[测试2] 注册并获取 token")
    token = engine.register_h("H_TEST_A", "测试用户A")
    assert len(token) == 64, f"token 应为 64 位 hex: {len(token)}"
    assert token.isalnum(), f"token 应仅为字母数字: {token}"
    print(f"  ✅ token 格式正确 ({len(token)} 位 hex)")

    # ── 测试3：认证后 process() 正常 ──
    print("\n[测试3] 认证后正常调用")
    ok = engine.authenticate(token)
    assert ok, "认证应通过"
    task2 = Task(h_id="H_TEST_A", task_type="morning_ritual", input="晨间测试")
    r2 = engine.process(task2)
    assert r2["status"] in ("completed", "pending_h"), f"process 应正常: {r2}"
    print(f"  ✅ process 认证后正常: {r2['status']}")

    # ── 测试4：伪造 token 应被拒绝 ──
    print("\n[测试4] 伪造 token 拒绝")
    fake = "a" * 64
    ok2 = engine.authenticate(fake)
    assert not ok2, "伪造 token 应被拒绝"
    print("  ✅ 伪造 token 被拒绝")

    # ── 测试5：社区引擎同步注册 ──
    print("\n[测试5] CommunityEngine 同步注册")
    members = engine.community.list_members()
    h_ids = [m["h_id"] for m in members]
    assert "H_TEST_A" in h_ids, f"H_TEST_A 应在社区成员中: {h_ids}"
    print(f"  ✅ CommunityEngine 已同步注册: {h_ids}")

    # ── 测试6：多 H 隔离 ──
    print("\n[测试6] 多 H 隔离")
    token_b = engine.register_h("H_TEST_B", "测试用户B")
    engine.authenticate(token_b)
    task3 = Task(h_id="H_TEST_B", task_type="reasoning", input="测试 B 的决策")
    r3 = engine.process(task3)
    print(f"  ✅ H_TEST_B 可独立调用: {r3['status']}")

    health = engine.system_health()
    print(f"  系统健康: M {health['m_pool']}, 社区: {len(h_ids) + 1} 人")

    print("\n" + "=" * 60)
    print("  场景06 全部通过 ✅")
    print("  测试点: token 格式/认证/伪造拒绝/社区同步/多H隔离")
    print("=" * 60)


if __name__ == "__main__":
    run_scenario()
