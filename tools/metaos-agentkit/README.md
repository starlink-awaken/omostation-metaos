# MetaOS AgentKit

`metaos-agentkit` is the personal, provider-native adapter for Codex and Claude Code.

It does **not** patch vendor binaries, replace CC Switch routing, or become a second MetaOS runtime. Its role is deliberately narrow:

- create global `~/.metaos/agentkit/` and project `.metaos/agentkit/` projections;
- inject marker-bounded provider rules into native instruction files;
- link lightweight MetaOS Skills into native skill locations;
- create provider-local projections of canonical `AgentSession` objects;
- call the root MetaOS runtime for gate, approval, lifecycle state, assets, decisions, and trace;
- launch an existing `codex` or `claude` command only after MetaOS permits it.

## Architecture

```text
AgentKit (provider adapter)
  → metaos-agent prepare
      → SEngine / DecisionGate / DLayer / Trace
  → provider launch
  → metaos-agent finalize
```

Operational risk (`R0`–`R4`), execution mode (`observe` / `propose` / `stage` / `commit`), dynamic Gate decision (`green` / `yellow` / `red`), and human confirmation are separate dimensions.

## Quick start

From the `omostation-metaos` repository:

```bash
cd tools/metaos-agentkit
uv run metaos-agentkit init --global --provider codex,claude --apply

cd /path/to/project
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit init --local --provider codex,claude --apply

uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit task new "Fix login TypeScript error" --risk R2 --mode stage

# Preview only: does not evaluate Gate or start a provider.
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit launch codex --mode stage -- --help

# Real launch: Gate is evaluated first. A blocked session is never launched.
uv run --directory /path/to/omostation-metaos/tools/metaos-agentkit \
  metaos-agentkit launch codex --mode stage --execute
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
| Provider configuration | `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, native skill links | marker-bounded AgentKit blocks only |

Provider-local files are projections/caches. Canonical authorization, decisions, assets, lifecycle state, and traces are written by root MetaOS.

## Safety model

- `init` defaults to preview mode; `--apply` is required for file mutations.
- The project initializer adds `.metaos/` only to `.git/info/exclude`, never to a shared `.gitignore`.
- `launch` defaults to preview; `--execute` performs MetaOS `prepare` before provider execution.
- A `yellow + commit` session is blocked until `task approve` records human confirmation through the existing MetaOS path.
- A provider process exit does not finalize a task. `task finalize` records actual verification evidence.
- Prompt rules are guidance. Codex sandbox/approvals, Claude permissions/hooks, MCP allowlists, Docker mounts, OAuth, and secret storage remain the real enforcement layer.

## Commands

```bash
metaos-agentkit init --global --provider codex,claude [--apply]
metaos-agentkit init --local --path /repo --provider codex,claude [--apply]
metaos-agentkit status [--path /repo]
metaos-agentkit task new "Description" --risk R2 --mode stage [--path /repo]
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

## Limitations

- Codex and Claude Code may evolve their instruction/skill discovery conventions. Verify generated files after provider upgrades.
- AgentKit does not automatically configure MCP permissions, Docker mounts, sandbox settings, Claude hooks, OAuth, or secret storage.
- Do not set broad filesystem or network permissions just because MetaOS rules are present.

## Development

```bash
uv run pytest -q
uv run python -m metaos_agentkit --help
```
