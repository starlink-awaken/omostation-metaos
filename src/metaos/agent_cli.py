"""CLI bridge for MetaOS-governed provider agent sessions.

This command owns governance state. Provider adapters may call it, but they
must not reimplement gate decisions or audit persistence themselves.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from metaos.core.engine import SEngine
from metaos.integrations.agent_runtime.cli_support import prepare_payload
from metaos.integrations.agent_runtime.contracts import AgentSession
from metaos.integrations.agent_runtime.service import AgentRuntimeService


ACCESS_LEVELS = ["owner", "private", "shared", "public"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metaos-agent", description="MetaOS-governed provider agent sessions")
    parser.add_argument("--data-dir", default="", help="MetaOS DLayer data directory")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Gate and persist a provider session")
    prepare.add_argument("--session-file", type=Path, required=True, help="AgentSession JSON input")
    prepare.add_argument("--out", type=Path, required=True, help="Prepared AgentSession JSON output")
    prepare.add_argument("--access-level", default="owner", choices=ACCESS_LEVELS)

    approve = sub.add_parser("approve", help="Approve a pending yellow-gate session")
    approve.add_argument("--session-file", type=Path, required=True)
    approve.add_argument("--out", type=Path, required=True)
    approve.add_argument("--comment", default="")
    approve.add_argument("--access-level", default="owner", choices=ACCESS_LEVELS)

    reject = sub.add_parser("reject", help="Reject a pending yellow-gate session")
    reject.add_argument("--session-file", type=Path, required=True)
    reject.add_argument("--out", type=Path, required=True)
    reject.add_argument("--comment", default="")
    reject.add_argument("--access-level", default="owner", choices=ACCESS_LEVELS)

    running = sub.add_parser("mark-running", help="Record an actual provider process launch")
    running.add_argument("--session-file", type=Path, required=True)
    running.add_argument("--out", type=Path, required=True)
    running.add_argument("--access-level", default="owner", choices=ACCESS_LEVELS)

    finalize = sub.add_parser("finalize", help="Record an actual provider outcome")
    finalize.add_argument("--session-file", type=Path, required=True, help="Prepared/running AgentSession JSON input")
    finalize.add_argument("--out", type=Path, required=True, help="Final AgentSession JSON output")
    finalize.add_argument("--summary", required=True)
    finalize.add_argument("--evidence", action="append", default=[])
    finalize.add_argument("--verification-passed", action="store_true")
    finalize.add_argument("--access-level", default="owner", choices=ACCESS_LEVELS)
    return parser


def _read_session(path: Path) -> AgentSession:
    return AgentSession.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_session(path: Path, session: AgentSession) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    engine = SEngine(data_dir=args.data_dir)
    runtime = AgentRuntimeService(engine)
    try:
        session = _read_session(args.session_file)
        if args.command == "prepare":
            session, context = runtime.prepare(session, access_level=args.access_level)
            _write_session(args.out, session)
            print(json.dumps(prepare_payload(session, context), ensure_ascii=False, indent=2))
            return 0 if session.status.value != "blocked" else 3
        if args.command == "approve":
            session = runtime.approve(session, comment=args.comment, access_level=args.access_level)
            _write_session(args.out, session)
            print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "reject":
            session = runtime.reject(session, comment=args.comment, access_level=args.access_level)
            _write_session(args.out, session)
            print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "mark-running":
            session = runtime.mark_running(session, access_level=args.access_level)
            _write_session(args.out, session)
            print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "finalize":
            session = runtime.finalize(
                session,
                summary=args.summary,
                evidence=args.evidence,
                verification_passed=args.verification_passed,
                access_level=args.access_level,
            )
            _write_session(args.out, session)
            print(json.dumps(session.to_dict(), ensure_ascii=False, indent=2))
            return 0 if args.verification_passed else 4
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
