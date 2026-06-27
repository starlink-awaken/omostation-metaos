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

Operational risk (`R0`–`R4`), execution mode (`observe` / `propose` / `stage` / `commit`), dynamic Gate decision (`green` / `yellow` / `red`), human confirmation, and capability profile are separate dimensions.

Read [Capability Profiles](../../docs/CAPABILITY-PROFILES.md) for the enforcement model.

## Quick start

From the `omostation-metaos` repository:

```bash
cd tools/metaos-agentkit
uv run metaos-agentkit init --global --provider codex,claude --apply

cd /path/to/project
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit init --local --provider codex,claude --apply

# R2 stage: defaults to repo-stage, creates a detached worktree on --execute.
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit task new "Fix login TypeScript error" --risk R2 --mode stage

# Preview only: does not evaluate Gate, create a worktree, render provider policy, or start a provider.
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit launch codex --mode stage -- --help

# Real launch: Gate is evaluated first. A blocked session is never launched.
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit launch codex --mode stage --execute
```

Read-only research with one explicitly named MCP server:

```bash
metaos-agentkit task new "Verify current provider settings" \
  --risk R1 --mode observe \
  --profile research-read \
  --allow-mcp web-reader
```

For a yellow commit session:

```bash
metaos-agentkit task approve --comment "Approved for this exact target"
metaos-agentkit launch codex --execute
metaos-agentkit task finalize \
  --summary "Patch applied and target tests passed" \
  --evidence "pytest tests/auth -q" \
  --verification-passed
```

## What it writes

| Scope | Paths | Ownership |
|---|---|---|
| MetaOS Core | `~/.metaos/data/` | `SEngine` / `DLayer` |
| AgentKit global | `~/.metaos/agentkit/` | AgentKit provider integration |
| AgentKit project | `.metaos/agentkit/` | provider-local projections, staging and audit working files |
| Session runtime | `.metaos/agentkit/tasks/<task>/runtime/` | generated Provider policy and persisted prepared context |
| Provider configuration | `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, native skill links | marker-bounded AgentKit blocks only |

Provider-local files are projections/caches. Canonical authorization, decisions, assets, lifecycle state, and traces are written by root MetaOS.

## Capability enforcement

- `core` / `repo-read`: read-only, no MCP server is allowed.
- `research-read`: only explicitly named MCP servers may be projected.
- `repo-stage`: Codex uses workspace write with network off; Claude uses a session overlay and PreToolUse Hook; both run in a detached worktree.
- `external-commit`: requires MetaOS commit validation and Gate/confirmation; only explicit MCP names are eligible.
- AgentKit rejects provider flags that could replace the session boundary, including Codex sandbox/config/approval flags and Claude settings/permission override flags.
- Discovered MCP servers not in the session allowlist are disabled for that launch.
- Provider exit is not success. Only `task finalize` with validation evidence records a final result.

## Commands

```bash
metaos-agentkit init --global --provider codex,claude [--apply]
metaos-agentkit init --local --path /repo --provider codex,claude [--apply]
metaos-agentkit status [--path /repo]
metaos-agentkit task new "Description" --risk R2 --mode stage \
  [--profile repo-stage] [--allow-mcp server] [--path /repo]
metaos-agentkit task approve [--comment "..."] [--path /repo]
metaos-agentkit task reject [--comment "..."] [--path /repo]
metaos-agentkit task finalize --summary "..." [--evidence "..."] [--verification-passed] [--path /repo]
metaos-agentkit launch codex --mode stage [--path /repo] [--execute] [-- <provider args>]
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
