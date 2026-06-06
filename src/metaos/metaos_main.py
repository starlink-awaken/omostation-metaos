"""MetaOS CLI 入口点 — pip install 后 `metaos` 命令即此"""

import argparse
import json
import sys
import time
from pathlib import Path

from cli import CLI  # type: ignore[import-not-found]

from metaos.cli.ssot_scan import scan_ssot  # type: ignore[import-not-found]
from metaos.core.engine import SEngine  # type: ignore[import-not-found]

DEFAULT_DATA_DIR = str(Path.home() / ".metaos" / "data")


# ── 会话管理 ──

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


def _ensure_engine(data_dir: str = "", h_id: str = "", name: str = ""):
    engine = SEngine(data_dir=data_dir or DEFAULT_DATA_DIR)
    backend = engine.m.backend_name
    if "ollama" in backend:
        info = engine.m.get_ollama_info()
        print(f"🧠 后端: ollama({info.get('model', '?')})", file=sys.stderr)
        print(file=sys.stderr)
    token = _get_token()
    if token and engine.authenticate(token):
        return engine
    if h_id:
        token = engine.register_h(h_id, name or h_id)
        _save_token(token)
        engine.authenticate(token)
    return engine


def _elapsed(start: float) -> str:
    t = time.time() - start
    if t < 60:
        return f"⏱  {t:.1f}s"
    return f"⏱  {t // 60:.0f}m {t % 60:.0f}s"


# ── 命令处理器 ──


def cmd_morning(args):
    engine = _ensure_engine(args.data_dir, args.h_id, args.name)
    cli = CLI(engine)
    start = time.time()
    r = cli.morning(args.text)
    print(f"\n{_elapsed(start)}", file=sys.stderr)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_evening(args):
    engine = _ensure_engine(args.data_dir, args.h_id, args.name)
    cli = CLI(engine)
    start = time.time()
    r = cli.evening(args.text)
    print(f"\n{_elapsed(start)}", file=sys.stderr)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_review(args):
    engine = _ensure_engine(args.data_dir, args.h_id)
    cli = CLI(engine)
    start = time.time()
    cli.review(args.action, args.expected, args.actual)
    print(f"\n{_elapsed(start)}", file=sys.stderr)


def cmd_gate(args):
    engine = _ensure_engine(args.data_dir, args.h_id)
    cli = CLI(engine)
    start = time.time()
    cli.gate(args.text)
    print(f"\n{_elapsed(start)}", file=sys.stderr)


def cmd_status(args):
    engine = _ensure_engine(args.data_dir)
    cli = CLI(engine)
    start = time.time()
    cli.status()
    info = engine.m.get_ollama_info()
    print(f"\n后端: {engine.m.backend_name}")
    if info.get("available"):
        print(f"  Ollama: {info['model']}")
        print(f"  可用: {', '.join(info['detected_models'][:4])}")
    print(_elapsed(start))


def cmd_trace(args):
    engine = _ensure_engine(args.data_dir, args.h_id)
    cli = CLI(engine)
    cli.trace(args.decision_id)


def cmd_register(args):
    engine = SEngine(data_dir=args.data_dir or DEFAULT_DATA_DIR)
    token = engine.register_h(args.h_id, args.name or args.h_id)
    _save_token(token)
    print(f"✅ H '{args.h_id}' 注册成功")


def cmd_day(args):
    day = int(args.day)
    engine = _ensure_engine(args.data_dir, args.h_id or f"day{day}", args.name)
    cli = CLI(engine)
    print(f"\n{'=' * 50}")
    print(f"  📋 Day {day}")
    print(f"{'=' * 50}\n")
    start = time.time()
    if day == 1:
        cli.morning("今日最值得聚焦的认知点是？")
        cli.evening("今日最重要的认知收获是？")
    elif day == 2:
        cli.morning("今日焦点")
        cli.review("选择一个行动复盘", "预期结果", "实际结果")
    elif day == 3:
        cli.morning("今日焦点")
        cli.gate("需要判定的决策")
    elif day == 4:
        cli.morning("今日焦点")
        cli.evening("帮我提炼一条原则草稿")
    elif day == 5:
        cli.morning("今日焦点")
    elif day == 6:
        cli.review("简化周复盘", "本周预期", "本周实际")
    elif day == 7:
        cli.morning("今日焦点")
        cli.evening("系统启动复盘")
    else:
        print("Day 仅支持 1-7")
    print(f"\n✅ Day {day} 完成  {_elapsed(start)}")
    return engine


def cmd_ssot(args):
    import os

    base_dir = args.path or os.path.join(os.path.dirname(__file__), "..")
    entries = scan_ssot(base_dir)
    total = len(entries)
    has = sum(1 for e in entries if e["ssot"])
    print(f"SSOT 覆盖率: {round(has / total * 100, 1)}%  ({has}/{total})")
    if args.verbose:
        for e in entries:
            if not e["ssot"]:
                print(f"  ⬜ {e['file']}")


# ── 主 CLI ──


def main():
    parser = argparse.ArgumentParser(
        prog="metaos",
        description="MetaOS 认知操作系统 — CLI",
        epilog="""示例:
  metaos register h_main         # 首次注册
  metaos morning "今日焦点"       # 晨间仪式
  metaos day 1                   # Day1 启动
  metaos status                  # 体系健康度
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data-dir", default="", help="数据目录")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("morning", help="晨间仪式")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--h-id", default="")
    p.add_argument("--name", default="")

    p = sub.add_parser("evening", help="晚间整合")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--h-id", default="")
    p.add_argument("--name", default="")

    p = sub.add_parser("review", help="微粒复盘")
    p.add_argument("action", help="行动描述")
    p.add_argument("expected", help="预期结果")
    p.add_argument("actual", help="实际结果")
    p.add_argument("--h-id", default="")

    p = sub.add_parser("gate", help="决策门控")
    p.add_argument("text", help="需要判定的决策")
    p.add_argument("--h-id", default="")

    p = sub.add_parser("status", help="体系健康度")
    sub.add_parser("trace", help="最近决策日志")
    sub.add_parser("logout", help="登出")
    sub.add_parser("onboard", help="交互式启动向导（自动检测中断天数）")
    sub.add_parser("dashboard", help="生成 HTML 仪表盘")

    p = sub.add_parser("register", help="注册新 H")
    p.add_argument("h_id", help="H ID")
    p.add_argument("--name", default="")

    p = sub.add_parser("day", help="启动指南日课")
    p.add_argument("day", help="天数（1-7）")
    p.add_argument("--h-id", default="")
    p.add_argument("--name", default="")

    p = sub.add_parser("ssot", help="SSOT 覆盖扫描")
    p.add_argument("--path", default="")
    p.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    handlers = {
        "morning": cmd_morning,
        "evening": cmd_evening,
        "review": cmd_review,
        "gate": cmd_gate,
        "status": cmd_status,
        "trace": cmd_trace,
        "register": cmd_register,
        "logout": lambda a: (TOKEN_FILE.unlink(missing_ok=True), print("✅ 已登出")),
        "onboard": lambda a: __import__("onboard").run(),
        "dashboard": lambda a: __import__("dashboard").main(),
        "day": cmd_day,
        "ssot": cmd_ssot,
    }

    fn = handlers.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
