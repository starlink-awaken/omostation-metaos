"""CLI for initializing MetaOS AgentKit without modifying provider binaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .service import (
    Plan,
    approve_task,
    create_task,
    finalize_task,
    install_global,
    install_local,
    launch,
    normalize_providers,
    reject_task,
    status,
    uninstall_global,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metaos-agentkit", description="MetaOS AgentKit bootstrapper for Codex and Claude Code")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Preview or apply global/project initialization")
    scope = p_init.add_mutually_exclusive_group(required=True)
    scope.add_argument("--global", dest="global_scope", action="store_true")
    scope.add_argument("--local", dest="local_scope", action="store_true")
    p_init.add_argument("--provider", default="codex,claude", help="comma-separated: codex,claude")
    p_init.add_argument("--path", type=Path, default=Path.cwd(), help="project root for --local")
    p_init.add_argument("--apply", action="store_true", help="perform writes; default is preview")

    p_status = sub.add_parser("status", help="Show MetaOS installation status")
    p_status.add_argument("--path", type=Path, default=Path.cwd())

    p_task = sub.add_parser("task", help="Manage canonical MetaOS AgentSession projections")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)
    p_new = task_sub.add_parser("new", help="Create a provider-local AgentSession projection")
    p_new.add_argument("description")
    p_new.add_argument("--risk", default="R0")
    p_new.add_argument("--mode", default="observe")
    p_new.add_argument("--path", type=Path, default=Path.cwd())

    p_approve = task_sub.add_parser("approve", help="Approve the latest pending yellow-gate session")
    p_approve.add_argument("--comment", default="")
    p_approve.add_argument("--path", type=Path, default=Path.cwd())

    p_reject = task_sub.add_parser("reject", help="Reject the latest pending yellow-gate session")
    p_reject.add_argument("--comment", default="")
    p_reject.add_argument("--path", type=Path, default=Path.cwd())

    p_finalize = task_sub.add_parser("finalize", help="Record a verified or failed provider outcome")
    p_finalize.add_argument("--summary", required=True)
    p_finalize.add_argument("--evidence", action="append", default=[])
    p_finalize.add_argument("--verification-passed", action="store_true")
    p_finalize.add_argument("--path", type=Path, default=Path.cwd())

    p_launch = sub.add_parser("launch", help="Prepare through MetaOS, then launch a provider")
    p_launch.add_argument("provider", choices=["codex", "claude"])
    p_launch.add_argument("--mode", choices=["observe", "propose", "stage", "commit"])
    p_launch.add_argument("--path", type=Path, default=Path.cwd())
    p_launch.add_argument("--execute", action="store_true", help="gate and run provider; default is preview")

    p_uninstall = sub.add_parser("uninstall", help="Remove only MetaOS-managed global blocks and symlinks")
    p_uninstall.add_argument("--global", dest="global_scope", action="store_true", required=True)
    p_uninstall.add_argument("--provider", default="codex,claude")
    p_uninstall.add_argument("--apply", action="store_true")
    return parser


def _show_plans(plans: list[Plan], apply: bool) -> None:
    mode = "APPLY" if apply else "PREVIEW"
    print(f"{mode}: {len(plans)} planned operation(s)")
    for plan in plans:
        print(f"- {plan.action:9} {plan.target}  [{plan.detail}]")
    if not apply:
        print("Re-run with --apply to write changes.")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args, unknown = parser.parse_known_args(argv)
    if unknown and args.command != "launch":
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    home = args.home.expanduser().resolve()
    try:
        if args.command == "init":
            providers = normalize_providers(args.provider)
            if args.global_scope:
                _show_plans(install_global(home=home, providers=providers, apply=args.apply), args.apply)
            else:
                project = args.path.expanduser().resolve()
                _show_plans(install_local(project=project, home=home, providers=providers, apply=args.apply), args.apply)
            return 0
        if args.command == "status":
            print(json.dumps(status(project=args.path.expanduser(), home=home), ensure_ascii=False, indent=2))
            return 0
        if args.command == "task":
            project = args.path.expanduser()
            if args.task_command == "new":
                print(create_task(project=project, description=args.description, risk=args.risk, mode=args.mode))
                return 0
            if args.task_command == "approve":
                print(approve_task(project=project, home=home, comment=args.comment))
                return 0
            if args.task_command == "reject":
                print(reject_task(project=project, home=home, comment=args.comment))
                return 0
            if args.task_command == "finalize":
                print(
                    finalize_task(
                        project=project,
                        home=home,
                        summary=args.summary,
                        evidence=args.evidence,
                        verification_passed=args.verification_passed,
                    )
                )
                return 0 if args.verification_passed else 4
        if args.command == "launch":
            pass_through = unknown
            if pass_through[:1] == ["--"]:
                pass_through = pass_through[1:]
            return launch(
                provider=args.provider,
                project=args.path.expanduser(),
                home=home,
                mode=args.mode,
                provider_args=pass_through,
                execute=args.execute,
            )
        if args.command == "uninstall":
            providers = normalize_providers(args.provider)
            _show_plans(uninstall_global(home=home, providers=providers, apply=args.apply), args.apply)
            return 0
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
