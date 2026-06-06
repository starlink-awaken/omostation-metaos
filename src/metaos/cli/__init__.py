"""MetaOS CLI——行动协议的命令行接口"""

import json
import os
from datetime import datetime
from pathlib import Path

from metaos.core.engine import SEngine  # type: ignore[import-not-found]
from metaos.core.types import Principle, Task, TaskType  # type: ignore[import-not-found]


class CLI:
    """日课仪式·微粒复盘·决策门控·周检·状态查询"""

    def __init__(self, engine: SEngine):
        self.engine = engine

    def morning(self, h_note: str = "", access_level: str = "public"):
        """晨间仪式——V6#3 修复：传递 access_level"""
        input_text = h_note or "晨间启动"
        task = Task(
            h_id=self.engine.current_h.h_id,
            task_type=TaskType.MORNING_RITUAL.value,
            input=input_text,
        )
        result = self.engine.process(task, access_level=access_level)
        print(f"\n🌅 晨间仪式 ({datetime.now().strftime('%m-%d %H:%M')})")
        print(f"{'=' * 40}")
        print(result.get("output", ""))
        if result.get("immune_alert"):
            print(f"\n⚠️  {result['immune_alert']}")

        # 元认知自问
        print("\n❓ 元认知问题：今天我最可能出现的认知偏误是什么？")
        return result

    def evening(self, day_log: str = "", access_level: str = "public"):
        input_text = day_log or "晚间整合"
        task = Task(
            h_id=self.engine.current_h.h_id,
            task_type=TaskType.EVENING_REVIEW.value,
            input=input_text,
        )
        result = self.engine.process(task, access_level=access_level)
        print(f"\n🌙 晚间整合 ({datetime.now().strftime('%m-%d %H:%M')})")
        print(f"{'=' * 40}")
        print(result.get("output", ""))

        # 检查待确认
        overdue = self.engine.check_pending_reviews()
        if overdue:
            print(f"\n⚠️  有 {len(overdue)} 个黄灯决策超时，已自动冻结")

        # 元认知自问
        print("\n❓ 元认知问题：今天思考质量如何评分（1-10）？")

        return result

    def review(self, action_desc: str, expected: str, actual: str, access_level: str = "public"):
        input_text = f"【复盘】行动: {action_desc} 预期: {expected} 实际: {actual}"
        task = Task(
            h_id=self.engine.current_h.h_id,
            task_type=TaskType.MICRO_REVIEW.value,
            input=input_text,
        )
        result = self.engine.process(task, access_level=access_level)
        print("\n📋 微粒复盘")
        print(f"{'=' * 40}")
        print(result.get("output", ""))

        # P1：自动将复盘输出的经验教训存入原则库
        output = result.get("output", "")
        h_id = self.engine.current_h.h_id
        if output and "教训" in output or "原则" in output or "lesson" in output.lower():
            # 提取前 100 字作为原则草稿
            lesson_text = output[:100].replace("\n", " ")
            p = Principle(
                content=lesson_text,
                source_h_id=h_id,
                source_experience=input_text[:80],
                applicability_tags=["micro_review", "auto"],
            )
            try:
                self.engine.d.save_principle(p)
                print(f"\n📌 经验教训已自动存入 D_私有（原则 ID: {p.principle_id[:8]}）")
            except Exception:
                pass  # 存失败不阻塞主流程

        return result

    def gate(self, decision_desc: str, access_level: str = "public") -> str:
        task = Task(
            h_id=self.engine.current_h.h_id,
            task_type="reasoning",
            input=decision_desc,
        )
        result = self.engine.process(task, access_level=access_level)
        level = result.get("level", "green")
        labels = {"red": "🔴 红灯区", "yellow": "🟡 黄灯区", "green": "🟢 绿灯区"}
        print(f"\n🚦 决策门控: {labels.get(level, '未知')}")
        print(f"{'=' * 40}")
        print(f"决策: {decision_desc[:80]}")
        print(f"级别: {level}")
        print(f"消息: {result.get('message', '')}")
        return level

    def status(self):
        """体系健康度"""
        health = self.engine.system_health()
        print("\n📊 体系健康度")
        print(f"{'=' * 40}")
        for k, v in health.items():
            print(f"  {k}: {v}")
        return health

    def trace(self, decision_id: str = ""):
        """查询决策日志"""
        if decision_id:
            trace = self.engine.d.get_asset_trace(decision_id)
            print(json.dumps(trace, indent=2, ensure_ascii=False))
        else:
            decisions = self.engine.d.get_decisions(self.engine.current_h.h_id, 10)
            print(f"\n📝 最近决策 ({len(decisions)} 条)")
            print(f"{'=' * 40}")
            for d in decisions:
                flag = "⏳" if d.outcome_pending_review else "✅"
                print(f"  {flag} {d.timestamp.strftime('%m-%d %H:%M')} [{d.level}] {d.description[:40]}")

    def status(self):  # noqa: F811
        """体系健康度——含后端信息"""
        health = self.engine.system_health()
        print("\n📊 体系健康度")
        print(f"{'=' * 40}")
        for k, v in health.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for sk, sv in v.items():
                    print(f"    {sk}: {sv}")
            else:
                print(f"  {k}: {v}")
        return health

    def ssot_scan(self, base_dir: str = "") -> dict:
        """扫描文档目录的 SSOT 覆盖完整性"""
        from cli.ssot_scan import scan_ssot  # type: ignore[import-not-found]

        base = base_dir or os.path.join(os.path.dirname(__file__), "..", "..")
        entries = scan_ssot(base)
        has = sum(1 for e in entries if e["ssot"])
        total = len(entries)
        coverage = round(has / total * 100, 1) if total > 0 else 0

        print("\n🔍 SSOT 覆盖扫描")
        print(f"{'=' * 40}")
        print(f"  文件总数: {total}")
        print(f"  有 SSOT:  {has}")
        print(f"  覆盖率:   {coverage}%")

        missing = [e for e in entries if not e["ssot"]]
        if missing:
            print(f"\n  缺少 SSOT 声明的文件 ({len(missing)}):")
            for e in missing[:10]:
                print(f"    ⬜ {e['file']}")
            if len(missing) > 10:
                print(f"    ... 还有 {len(missing) - 10} 个")

        return {
            "total": total,
            "with_ssot": has,
            "coverage_pct": coverage,
            "missing": [e["file"] for e in missing],
        }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for MetaOS."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="metaos",
        description="MetaOS — 编排/治理层：决策门控、免疫监控、路由、数字资产引擎",
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    sub.add_parser("status", help="体系健康度")
    sub.add_parser("trace", help="最近决策日志")

    p_gate = sub.add_parser("gate", help="决策门控")
    p_gate.add_argument("decision", help="决策描述")

    p_review = sub.add_parser("review", help="微粒复盘")
    p_review.add_argument("action", help="行动描述")
    p_review.add_argument("expected", help="预期结果")
    p_review.add_argument("actual", help="实际结果")

    p_run = sub.add_parser("run", help="运行 YAML 定义的工作流")
    p_run.add_argument("file", help="YAML 工作流定义文件路径")

    sub.add_parser("ssot-scan", help="SSOT 覆盖扫描")

    args = parser.parse_args(argv if argv else None)

    if args.command is None:
        parser.print_help()
        return 0

    from metaos.core.engine import SEngine  # 修复了原来的 type 错误

    engine = SEngine(data_dir=str(Path.home() / ".metaos" / "data"))
    cli = CLI(engine)

    if args.command == "status":
        cli.status()
    elif args.command == "trace":
        cli.trace()
    elif args.command == "gate":
        cli.gate(args.decision)
    elif args.command == "review":
        cli.review(args.action, args.expected, args.actual)
    elif args.command == "run":
        from metaos.core.workflow_parser import WorkflowParser
        try:
            # 系统级自动鉴权（Workflow 以 metaos_system 身份运行）
            token = engine.register_h("metaos_system", "MetaOS Workflow Runner")
            engine.authenticate(token)
            
            parser_engine = WorkflowParser(engine)
            wf = parser_engine.parse_file(args.file)
            print(f"\n🚀 启动工作流: {wf.workflow_id} ({len(wf.nodes)} 节点)")
            wf.run()
            
            print("\n🏁 工作流执行报告:")
            for nid, node in wf.nodes.items():
                icon = "✅" if node.status == "completed" else "❌"
                print(f"  {icon} [{nid}] {node.status}")
                if node.output:
                    print(f"       → {node.output[:120]}...")
        except Exception as e:
            print(f"❌ 工作流执行失败: {e}")
    elif args.command == "ssot-scan":
        cli.ssot_scan()

    return 0
