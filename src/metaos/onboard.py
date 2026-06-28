"""MetaOS Onboard — 交互式启动向导"""

import json
import time
from pathlib import Path

from metaos.cli import CLI  # type: ignore[import-not-found]
from metaos.core.engine import SEngine  # type: ignore[import-not-found]

DEFAULT_DATA_DIR = str(Path.home() / ".metaos" / "data")
ONBOARD_FILE = Path.home() / ".metaos" / "onboard.json"
TOKEN_FILE = Path.home() / ".metaos" / ".token"


def _get_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return ""


def _save_token(token: str):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token)
    # ⚠️ 生产环境应使用加密存储（如 keyring / 加密文件）
    TOKEN_FILE.chmod(0o600)


def _load_state() -> dict:
    if ONBOARD_FILE.exists():
        try:
            return json.loads(ONBOARD_FILE.read_text())
        except Exception:  # defensive fallback  # noqa: BLE001
            pass
    return {"day": 0, "last_active": None, "completed": False}


def _save_state(state: dict):
    ONBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    ONBOARD_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _detect_interrupt(state: dict) -> int:
    """检测中断天数"""
    if not state.get("last_active"):
        return 0
    from datetime import datetime

    last = datetime.fromisoformat(state["last_active"])
    elapsed = (datetime.now() - last).days
    return elapsed


def _recover_path(days_gone: int) -> int:
    """推荐恢复天数"""
    if days_gone <= 2:
        return 0  # 不退回
    elif days_gone <= 5:
        return -3  # 退回 3 天
    else:
        return -99  # 从头开始


def run():
    state = _load_state()
    engine = SEngine(data_dir=DEFAULT_DATA_DIR)
    token = _get_token()
    if not token:
        print("=" * 50)
        print("  🚀 MetaOS 启动向导")
        print("=" * 50)
        print()
        h_id = input("你的 H ID（默认: h_main）: ").strip() or "h_main"
        name = input("你的显示名称（默认: 用户）: ").strip() or "用户"
        token = engine.register_h(h_id, name)
        _save_token(token)
        engine.authenticate(token)
        print(f"\n✅ H '{h_id}' 注册成功\n")
    else:
        engine.authenticate(token)
        print(f"✅ 已恢复 session: {engine._current_h_id}\n")

    cli = CLI(engine)

    # 检测中断
    days_gone = _detect_interrupt(state)
    if days_gone > 0 and state["day"] > 0:
        print(f"⚠️  你已中断 {days_gone} 天（上次在 Day{state['day']}）")
        rec = _recover_path(days_gone)
        if rec == 0:
            print(f"   建议：从 Day{state['day']} 继续\n")
        elif rec == -3:
            resume = max(1, state["day"] - 3)
            print(f"   建议：退回 Day{resume}\n")
        else:
            print("   建议：从 Day1 重新开始\n")
        choice = input("按回车继续，或输入要跳转的天数 (1-7): ").strip()
        if choice.isdigit():
            start_day = max(1, min(7, int(choice)))
        elif rec == -99:
            start_day = 1
        elif rec == -3:
            start_day = max(1, state["day"] - 3)
        else:
            start_day = state["day"]
    else:
        start_day = 1

    print()
    print(f"📋 从 Day{start_day} 开始\n")

    for day in range(start_day, 8):
        print(f"\n{'=' * 50}")
        print(f"  📋 Day {day}")
        print(f"{'=' * 50}")
        day_start = time.time()

        if day == 1:
            input("🌅 晨间仪式（按回车开始）...")
            cli.morning("今日最值得聚焦的认知点是？")
            input("\n🌙 晚间整合（按回车开始）...")
            cli.evening("今日最重要的认知收获是什么？")

        elif day == 2:
            input("🌅 晨间（按回车）...")
            cli.morning("今日焦点")
            action = input("\n📋 要复盘的行动: ") or "今天的一个行动"
            exp = input("   预期结果: ") or "X"
            act = input("   实际结果: ") or "Y"
            cli.review(action, exp, act)

        elif day == 3:
            input("🌅 晨间（按回车）...")
            cli.morning("今日焦点")
            dec = input("\n🚦 需要判定的决策: ") or "今天的一个决策"
            cli.gate(dec)

        elif day == 4:
            input("🌅 晨间（按回车）...")
            cli.morning("今日焦点")
            input("\n🌙 晚间审核教训（按回车）...")
            cli.evening("帮我提炼一条原则草稿")

        elif day == 5:
            input("🌅 晨间（按回车）...")
            cli.morning("今日焦点")
            print("\n💡 提示：审视近 5 天积累的经验教训清单")
            print("   运行: metaos trace")

        elif day == 6:
            input("🌅 晨间（按回车）...")
            cli.morning("今日焦点")
            print("\n📊 简化周复盘")
            cli.review("本周复盘", "预期进展", "实际进展")

        elif day == 7:
            input("🌅 晨间（按回车）...")
            cli.morning("今日焦点")
            input("\n🎯 闭环仪式（按回车）...")
            cli.evening("系统启动复盘")
            print(f"\n{'=' * 50}")
            print("  🎉 启动完成！你已经完成了 MetaOS 启动周期")
            print(f"{'=' * 50}")

        elapsed = time.time() - day_start
        state["day"] = day
        state["last_active"] = __import__("datetime").datetime.now().isoformat()
        _save_state(state)
        print(f"\n✅ Day {day} 完成  ⏱ {elapsed:.0f}s")

        if day < 7:
            cont = input("\n继续下一 Day？(Y/n): ").strip().lower()
            if cont == "n":
                print("\n⏸  已暂停。下次运行 metaos onboard 会从中断处继续")
                break

    state["completed"] = day >= 7
    _save_state(state)
    print(f"\n🧠 后端: {engine.m.backend_name}")


def main():
    try:
        run()
    except KeyboardInterrupt:
        print("\n\n⏸  已暂停。下次运行 `metaos onboard` 会从中断处继续")


if __name__ == "__main__":
    main()
