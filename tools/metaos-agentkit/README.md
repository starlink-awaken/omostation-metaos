# MetaOS AgentKit

`metaos-agentkit` is the personal, provider-native adapter for Codex and Claude Code.

It does **not** patch vendor binaries, replace CC Switch routing, or become a second MetaOS runtime. Its role is deliberately narrow:

- create global `~/.metaos/agentkit/` and project `.metaos/agentkit/` projections;
- inject marker-bounded provider rules into native instruction files;
- link lightweight MetaOS Skills into native skill locations;
- create provider-local projections of canonical `AgentSession` objects;
- call the root MetaOS runtime for Gate, approval, lifecycle state, assets, decisions, and trace;
- render the resolved capability profile into a one-session Codex or Claude Code runtime boundary;
- launch an existing `codex` or `claude` command only after MetaOS permits it.

## Architecture

```text
AgentKit (provider adapter)
  → metaos-agent prepare
      → SEngine / DecisionGate / DLayer / Trace
  → session capability renderer
      → sandbox / approval / worktree / MCP allowlist / Hook
  → provider launch
  → metaos-agent finalize
```

Operational risk (`R0`–`R4`), execution mode (`observe` / `propose` / `stage` / `commit`), dynamic Gate decision (`green` / `yellow` / `red`), human confirmation, target binding, and capability profile are separate dimensions.

Read [Capability Profiles](../../docs/CAPABILITY-PROFILES.md) and [Task Lifecycle](../../docs/TASK-LIFECYCLE.md) for enforcement and operational details.

## Quick start

From the `omostation-metaos` repository:

```bash
cd tools/metaos-agentkit
uv run metaos-agentkit init --global --provider codex,claude --apply

cd /path/to/project
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit init --local --provider codex,claude --apply

# R2 stage defaults to repo-stage and creates a detached worktree on --execute.
TASK=$(uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit task new "Fix login TypeScript error" --risk R2 --mode stage)

metaos-agentkit task list
metaos-agentkit launch codex --task "${TASK##*/}" --mode stage --execute
metaos-agentkit task finalize --task "${TASK##*/}" \
  --summary "Focused tests passed" \
  --evidence "pytest tests/auth -q" \
  --verification-passed
```

Read-only research with one explicit MCP tool:

```bash
metaos-agentkit task new "Verify current provider settings" \
  --risk R1 --mode observe \
  --profile research-read \
  --allow-mcp web-reader:open
```

High-risk external commit with a short-lived target binding:

```bash
metaos-agentkit task new "Create a calendar event" \
  --risk R3 --mode commit --profile external-commit \
  --target-kind calendar_event \
  --target calendar:primary \
  --operation create_event \
  --scope recipient:alice@example.com \
  --scope duration:30m \
  --expires-in-minutes 30 \
  --success-criterion "Calendar returns an event id" \
  --verify-expect "Event exists with Alice as attendee" \
  --rollback "Delete the newly created event" \
  --allow-mcp calendar:create_event

# List, then use the exact task ID for all high-risk lifecycle actions.
metaos-agentkit task list
metaos-agentkit task approve --task task-... --comment "Approved only for Alice, 30 minutes"
metaos-agentkit launch claude --task task-... --execute
metaos-agentkit task finalize --task task-... \
  --summary "Event created and verified" \
  --verification-passed
```

## What it writes

| Scope | Paths | Ownership |
|---|---|---|
| MetaOS Core | `~/.metaos/data/` | `SEngine` / `DLayer` |
| AgentKit global | `~/.metaos/agentkit/` | AgentKit provider integration |
| AgentKit project | `.metaos/agentkit/` | provider-local projections, staging and audit working files |
| Session runtime | `.metaos/agentkit/tasks/<task>/runtime/` | generated Provider policy and persisted prepared context |
| Session audit | `.metaos/agentkit/tasks/<task>/audit/` | launch plan, provider exit, bounded finalization evidence |
| Provider configuration | `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, native skill links | marker-bounded AgentKit blocks only |

Provider-local files are projections/caches. Canonical authorization, decisions, assets, lifecycle state, target-bound approvals, and traces are written by root MetaOS.

## Capability enforcement

- `core` / `repo-read`: read-only, no MCP server is allowed.
- `research-read`: explicitly named MCP servers or tools may be projected.
- `repo-stage`: Codex uses workspace write with network off; Claude uses a session overlay and PreToolUse Hook; both run in a detached worktree.
- `high-risk-stage`: R3/R4 planning or rehearsal stays in an isolated worktree with no external effects.
- `external-commit`: R3/R4 commit requires an expiring target binding and explicit human confirmation, even where the dynamic Gate initially evaluates green.
- AgentKit rejects provider flags that could replace the session boundary, including Codex sandbox/config/approval flags and Claude settings/permission override flags.
- Discovered MCP servers not in the session allowlist are disabled for that launch.
- Claude enforces server/tool-level MCP requests in the Hook. Codex enforces server disablement and per-tool prompting for an allowed server; it does not yet have an equal tool-deny projection.
- Provider exit is not success. `task finalize` persists a bounded evidence bundle, but `--verification-passed` remains an explicit success assertion.

## Commands

```bash
metaos-agentkit init --global --provider codex,claude [--apply]
metaos-agentkit init --local --path /repo --provider codex,claude [--apply]
metaos-agentkit status [--path /repo]
metaos-agentkit task new "Description" --risk R2 --mode stage \
  [--profile repo-stage] [--allow-mcp server[:tool]] [--path /repo]
metaos-agentkit task list [--all] [--path /repo]
metaos-agentkit task approve --task task-... [--comment "..."] [--path /repo]
metaos-agentkit task reject --task task-... [--comment "..."] [--path /repo]
metaos-agentkit task finalize --task task-... --summary "..." \
  [--evidence "..."] [--verification-passed] [--path /repo]
metaos-agentkit task archive --task task-... [--apply] [--path /repo]
metaos-agentkit task cleanup --older-than 14 [--apply] [--path /repo]
metaos-agentkit launch codex --task task-... --mode stage [--path /repo] [--execute] [-- <provider args>]
metaos-agentkit uninstall --global --provider codex,claude [--apply]

# Root runtime bridge, installed with the main package:
metaos-agent prepare --session-file input.json --out prepared.json
metaos-agent approve --session-file prepared.json --out approved.json
metaos-agent mark-running --session-file approved.json --out running.json
metaos-agent finalize --session-file running.json --out final.json --summary "..." --verification-passed
```

## Limits

- The capability renderer is session-scoped. It does not rewrite your persistent CC Switch routing or default provider configuration.
- Docker socket/mount execution is intentionally not enabled by any built-in profile yet.
- Provider managed policy, operating-system ACLs, OAuth scopes, secret storage, and sandbox availability remain separate enforcement layers.
- Codex and Claude Code can evolve their instruction, sandbox, and MCP conventions. Run the provider smoke tests after upgrades.

## Development

```bash
uv run pytest -q
uv run python -m metaos_agentkit --help
```
