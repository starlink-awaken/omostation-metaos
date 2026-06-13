#!/usr/bin/env python3
"""MetaOS 命令行入口——交互式日课 + 状态管理"""

import argparse
import json
import os
import sys
from pathlib import Path

# 确保能找到 engine 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import CLI  # type: ignore[import-not-found]

from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.layers.admission_gateway import AdmissionGateway


def get_engine_and_cli(data_dir: str = "") -> tuple:
    """获取引擎实例（自动恢复持久化 session）"""
    engine = SEngine(data_dir=data_dir)
    cli = CLI(engine)
    return engine, cli


def cmd_morning(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    _ensure_auth(engine, args.h_id, args.name)
    r = cli.morning(args.text, access_level="public")
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_evening(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    _ensure_auth(engine, args.h_id, args.name)
    r = cli.evening(args.text, access_level="public")
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_review(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    _ensure_auth(engine, args.h_id, args.name)
    r = cli.review(args.action, args.expected, args.actual, access_level="public")
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_gate(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    _ensure_auth(engine, args.h_id, args.name)
    level = cli.gate(args.text, access_level="public")
    print(f"决策级别: {level}")


def cmd_status(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    if args.h_id:
        _ensure_auth(engine, args.h_id, args.name)
    health = cli.status()
    print()
    # 显示后端信息
    print(f"后端: {engine.m.backend_name}")
    ollama_info = engine.m.get_ollama_info()
    if ollama_info.get("available"):
        print(f"  Ollama: {ollama_info['model']} @ {ollama_info['endpoint']}")
        if ollama_info.get("detected_models"):
            print(f"  可用模型: {', '.join(ollama_info['detected_models'][:3])}")
    return health


def cmd_trace(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    if args.h_id:
        _ensure_auth(engine, args.h_id, args.name)
    cli.trace(args.decision_id)


def cmd_ssot(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    r = cli.ssot_scan()
    print(f"\nSSOT 覆盖率: {r['coverage_pct']}%  ({r['with_ssot']}/{r['total']})")
    if r["missing"]:
        print(f"缺失: {len(r['missing'])} 个文件")


def cmd_register(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    token = engine.register_h(args.h_id, args.name or args.h_id)
    # 保存 token 到文件，下次自动使用
    # ⚠️ 当前为明文存储 (chmod 600)，开发环境可接受但生产需加密
    # 建议: macOS → Keychain; Linux → keyring; 或加密文件 + 环境变量
    token_file = _get_token_file(args.data_dir)
    token_file.write_text(token)
    token_file.chmod(0o600)
    print(f"✅ H '{args.h_id}' 注册成功")
    print(f"Token: {token[:16]}... (已保存到 {token_file})")


def cmd_logout(args):
    engine, cli = get_engine_and_cli(args.data_dir)
    token = _load_token(args.data_dir)
    if token and engine.logout(token):
        token_file = _get_token_file(args.data_dir)
        if token_file.exists():
            token_file.unlink()
        print("✅ 已登出")
    else:
        print("ℹ️  未登录")


def cmd_admit(args):
    """(T3.2) 触发决策网关准入控制，评估 Agent / Domain"""
    gateway = AdmissionGateway()
    # Mock extracting request capabilities from CLI args for demonstration
    req = {
        "domain": args.domain,
        "role": args.role,
        "declared_values": args.values.split(",") if args.values else [],
        "supports_otlp": args.otlp,
        "omo_audit_trail_id": args.audit_id,
        "capabilities": args.capabilities.split(",") if args.capabilities else []
    }
    result = gateway.evaluate_admission(req)
    if result["status"] == "admitted":
        print(f"✅ 准入通过 (Admitted): {result['reasons'][0]}")
    else:
        print("❌ 准入拦截 (Rejected):")
        for reason in result['reasons']:
            print(f"   - {reason}")
        sys.exit(1)


# ── 辅助函数 ──


def _get_token_file(data_dir: str = "") -> Path:
    base = Path(data_dir) if data_dir else Path.home() / ".metaos"
    base.mkdir(parents=True, exist_ok=True)
    return base / ".token"


def _load_token(data_dir: str = "") -> str:
    tf = _get_token_file(data_dir)
    if tf.exists():
        return tf.read_text().strip()
    return ""


def _ensure_auth(engine: SEngine, h_id: str = "", name: str = ""):
    """自动恢复或新建 session"""
    token = _load_token()
    if token and engine.authenticate(token):
        return
    if h_id:
        token = engine.register_h(h_id, name or h_id)
        # ⚠️ 生产环境应使用加密存储（如 keyring / 加密文件）
        tf = _get_token_file()
        tf.write_text(token)
        tf.chmod(0o600)
        engine.authenticate(token)
        return
    # fallback: 匿名模式
    pass


# ── 日课命令（Day1-Day7） ──


def cmd_day(args):
    """启动指南的日课可执行化"""
    day = int(args.day)
    engine, cli = get_engine_and_cli(args.data_dir)
    _ensure_auth(engine, args.h_id or f"day{day}_user", args.name or f"Day{day}")

    print(f"\n{'=' * 50}")
    print(f"  📋 Day {day} — 启动指南第 {day} 天")
    print(f"{'=' * 50}")
    print()

    if day == 1:
        print("目标：跑通一次晨间 + 一次晚间仪式")
        text = input("🌅 晨间引导语（回车用默认）: ") or "今日最值得聚焦的认知点是？"
        r = cli.morning(text)
        print(f"\n  状态: {r['status']}")
        print(f"  输出: {r.get('output', '')[:200]}")
        input("\n按回车继续晚间仪式...")
        text2 = input("🌙 晚间引导语（回车用默认）: ") or "今日最重要的认知收获是？"
        r2 = cli.evening(text2)
        print(f"\n  状态: {r2['status']}")
        print("\n✅ Day 1 完成")

    elif day == 2:
        print("目标：日课 + 至少 1 次微粒复盘")
        text = input("🌅 晨间引导语: ") or "今日焦点"
        cli.morning(text)
        print()
        action = input("📋 复盘的行动: ")
        expected = input("   预期结果: ")
        actual = input("   实际结果: ")
        r = cli.review(action, expected, actual)
        print(f"\n  复盘输出: {r.get('output', '')[:200]}")
        text2 = input("\n🌙 晚间引导语: ") or "今日收获"
        cli.evening(text2)
        print("\n✅ Day 2 完成")

    elif day == 3:
        print("目标：日课 + 复盘 + 决策门控")
        text = input("🌅 晨间: ") or "今日焦点"
        cli.morning(text)
        decision = input("🚦 需要判定的决策: ")
        level = cli.gate(decision)
        print(f"  决策级别: {level}")
        print("\n✅ Day 3 完成 — 今天开始你已经有决策门控意识了")

    elif day == 4:
        print("目标：晚间审核经验教训")
        text = input("🌅 晨间: ") or "今日焦点"
        cli.morning(text)
        print("\n晚间请对 M 的回答做三轮审核：")
        print("  1. 这条经验教训可迁移吗？")
        print("  2. 有反例吗？")
        print("  3. 与已有原则冲突吗？")
        text2 = input("\n🌙 晚间引导语: ") or "帮我提炼一条原则草稿"
        r = cli.evening(text2)
        print(f"\n  输出: {r.get('output', '')[:200]}")
        print("\n✅ Day 4 完成")

    elif day == 5:
        print("目标：审视 D_私有 经验教训清单")
        cli.morning(input("🌅 晨间: ") or "今日焦点")
        input("\n对 M 说：列出我这5天的经验教训清单（按回车继续）")
        print("(数据查看请用: python3 metaos.py trace)")
        print("\n✅ Day 5 完成")

    elif day == 6:
        print("目标：简化版周复盘")
        counts = input("微粒复盘次数: ") or "0"
        lessons = input("经验教训条数: ") or "0"
        input("偏误提醒次数: ") or "0"
        r = cli.review("简化周复盘", f"本周复盘{counts}次", f"教训{lessons}条")
        print(f"  复盘输出: {r.get('output', '')[:200]}")
        print("\n✅ Day 6 完成")

    elif day == 7:
        print("目标：闭环仪式 — 回顾 7 天 + 下周规划")
        cli.morning(input("🌅 晨间: ") or "今日焦点")
        print("\n对 M 说：系统启动复盘")
        print("  哪些协议最容易执行？哪些最难坚持？")
        print("  下周的改进点是什么？")
        r = cli.evening("系统启动复盘")
        print(f"  输出: {r.get('output', '')[:300]}")
        print("\n✅ Day 7 完成！你已经完成了 MetaOS 启动周期")
        print("从第 2 周开始进入常规运营模式")

    else:
        print(f"❌ Day {day} 无效（支持 1-7）")


def cmd_interactive(args):
    """交互式 REPL 模式"""
    engine, cli = get_engine_and_cli(args.data_dir)
    token = _load_token(args.data_dir)
    if not token:
        h_id = input("首次使用，注册 H ID（默认: h_main）: ") or "h_main"
        name = input("显示名称（默认: 用户）: ") or "用户"
        token = engine.register_h(h_id, name)
        # ⚠️ 生产环境应使用加密存储（如 keyring / 加密文件）
        tf = _get_token_file(args.data_dir)
        tf.write_text(token)
        tf.chmod(0o600)
        print(f"✅ 已注册 {h_id}，token 已保存\n")
    engine.authenticate(token)

    print(f"MetaOS 交互模式 · 后端: {engine.m.backend_name}")
    print("可用命令: morning / evening / review / gate / status / trace / day / help / exit")
    print()
    while True:
        try:
            cmd = input("metaos> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not cmd:
            continue
        if cmd in ("exit", "quit", "q"):
            break
        if cmd == "help":
            print("  morning [文本]  — 晨间仪式")
            print("  evening [文本] — 晚间整合")
            print("  review [行动] [预期] [实际] — 微粒复盘")
            print("  gate [决策]    — 决策门控")
            print("  status         — 体系健康度")
            print("  trace [id]     — 决策日志")
            print("  day N          — 启动指南第 N 天")
            print("  help / exit    — 帮助/退出")
            continue
        if cmd == "status":
            cli.status()
            continue
        parts = cmd.split(maxsplit=3) if " " in cmd else [cmd, ""]
        if cmd == "status" or parts[0] == "status":
            cli.status()
        elif parts[0] == "morning":
            r = cli.morning(parts[1] if len(parts) > 1 else "")
            print(f"\n状态: {r['status']}")
        elif parts[0] == "evening":
            r = cli.evening(parts[1] if len(parts) > 1 else "")
            print(f"\n状态: {r['status']}")
        elif parts[0] == "review" and len(parts) >= 4:
            r = cli.review(parts[1], parts[2], parts[3])
        elif parts[0] == "gate":
            level = cli.gate(parts[1] if len(parts) > 1 else "")
            print(f"级别: {level}")
        elif parts[0] == "trace":
            cli.trace(parts[1] if len(parts) > 1 else "")
        elif parts[0] == "day":
            try:
                engine._current_h_id = ""
                nd = int(parts[1]) if len(parts) > 1 else 1
                cli2 = CLI(engine)
                # 执行 day 逻辑
                print(f"📋 Day {nd}")
                if nd == 1:
                    cli2.morning("今日最值得聚焦的认知点是？")
                    cli2.evening("今日最重要的认知收获是？")
                print("完成")
            except Exception as e:
                print(f"错误: {e}")
        else:
            print(f"未知命令: {cmd}")


# ── 主入口 ──


def main():
    parser = argparse.ArgumentParser(
        description="MetaOS 认知操作系统 — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 metaos.py morning "今日焦点"      # 晨间仪式
  python3 metaos.py day 1                    # 启动指南 Day1
  python3 metaos.py interactive              # 交互模式
  python3 metaos.py status                   # 体系健康度
        """,
    )
    parser.add_argument("--data-dir", default="", help="数据目录（默认临时目录）")

    subparsers = parser.add_subparsers(dest="command")

    # morning
    p = subparsers.add_parser("morning", help="晨间仪式")
    p.add_argument("text", nargs="?", default="", help="晨间引导语")
    p.add_argument("--h-id", default="", help="H ID（首次自动注册）")
    p.add_argument("--name", default="", help="显示名称")

    # evening
    p = subparsers.add_parser("evening", help="晚间整合")
    p.add_argument("text", nargs="?", default="", help="晚间引导语")
    p.add_argument("--h-id", default="")
    p.add_argument("--name", default="")

    # review
    p = subparsers.add_parser("review", help="微粒复盘")
    p.add_argument("action", help="行动描述")
    p.add_argument("expected", help="预期结果")
    p.add_argument("actual", help="实际结果")
    p.add_argument("--h-id", default="")

    # gate
    p = subparsers.add_parser("gate", help="决策门控")
    p.add_argument("text", help="需要判定的决策")
    p.add_argument("--h-id", default="")

    # status
    p = subparsers.add_parser("status", help="体系健康度")
    p.add_argument("--h-id", default="")

    # trace
    p = subparsers.add_parser("trace", help="决策日志")
    p.add_argument("decision_id", nargs="?", default="", help="决策 ID")
    p.add_argument("--h-id", default="")

    # ssot
    subparsers.add_parser("ssot", help="SSOT 覆盖扫描")

    # register
    p = subparsers.add_parser("register", help="注册新 H")
    p.add_argument("h_id", help="H ID")
    p.add_argument("--name", default="", help="显示名称")

    # logout
    p_logout = subparsers.add_parser("logout", help="退出登录")
    p_logout.set_defaults(func=cmd_logout)

    # day
    p = subparsers.add_parser("day", help="启动指南日课（1-7）")
    p.add_argument("day", help="天数")
    p.add_argument("--h-id", default="")
    p.add_argument("--name", default="")

    # interactive
    subparsers.add_parser("interactive", help="交互式 REPL 模式")
    subparsers.add_parser("shell", help="交互式 REPL 模式（同 interactive）")

    # admission
    p_admit = subparsers.add_parser("admit", help="Agent 准入网关 (eCOS v6.1 T3.2)")
    p_admit.add_argument("--domain", default="unknown", help="接入域名称")
    p_admit.add_argument("--role", default="unknown", help="运行角色 (generator/evaluator)")
    p_admit.add_argument("--values", default="", help="价值观声明 (逗号分隔)")
    p_admit.add_argument("--otlp", action="store_true", help="是否支持 OTLP")
    p_admit.add_argument("--audit-id", default="", help="OMO 审计标识")
    p_admit.add_argument("--capabilities", default="", help="特权需求声明")
    p_admit.set_defaults(func=cmd_admit)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 路由
    cmds = {
        "morning": cmd_morning,
        "evening": cmd_evening,
        "review": cmd_review,
        "gate": cmd_gate,
        "status": cmd_status,
        "trace": cmd_trace,
        "ssot": cmd_ssot,
        "register": cmd_register,
        "logout": cmd_logout,
        "day": cmd_day,
        "interactive": cmd_interactive,
        "shell": cmd_interactive,
    }

    fn = cmds.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
