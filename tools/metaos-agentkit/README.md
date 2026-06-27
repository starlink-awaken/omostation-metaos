# MetaOS AgentKit

`metaos-agentkit` turns the MetaOS personal workflow rules into a small, provider-native bootstrap layer for Codex and Claude Code.

It does **not** patch vendor binaries, replace CC Switch routing, or claim to be a hard security boundary. Instead it:

- creates global `~/.metaos/` and project `.metaos/` directories;
- injects marker-bounded provider rules into native instruction files;
- links lightweight MetaOS Skills into the native skill locations;
- creates machine-readable task envelopes for staged work;
- launches an existing `codex` or `claude` command with MetaOS task context;
- preserves existing provider files and supports a preview-first workflow.

## Quick start

```bash
cd tools/metaos-agentkit
uv run metaos-agentkit init --global --provider codex,claude --apply
cd /path/to/project
uv run metaos-agentkit init --local --provider codex,claude --apply
uv run metaos-agentkit task new "Fix login TypeScript error" --risk R2 --mode stage
uv run metaos-agentkit launch codex --mode stage
```

`init` defaults to preview mode. Only `--apply` writes files.

## What it writes

| Scope | Paths |
|---|---|
| Global | `~/.metaos/`, `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, native skill links |
| Project | `.metaos/`, `AGENTS.md`, `CLAUDE.local.md`, project-local skill links |

Provider file edits are bounded by `METAOS-AGENTKIT:BEGIN/END` markers. Existing content outside the markers is preserved. A backup is created before the first edit of each target file.

## Safety model

- Preview before write; `--apply` is required for mutations.
- The project initializer adds `.metaos/` only to `.git/info/exclude`, not to shared `.gitignore`.
- Task envelopes default to `observe` / `R0`; higher-risk tasks must be explicit.
- `launch` only sets environment variables and invokes the local provider command. It does not bypass provider approval, sandbox, MCP, network, or filesystem controls.
- Prompt rules are guidance. Use Codex sandbox / approvals and Claude Code permissions / hooks as enforcement.

## Commands

```bash
metaos-agentkit init --global --provider codex,claude [--apply]
metaos-agentkit init --local --path /repo --provider codex,claude [--apply]
metaos-agentkit status [--path /repo]
metaos-agentkit task new "Description" --risk R2 --mode stage [--path /repo]
metaos-agentkit launch codex --mode stage [--path /repo] [-- <provider args>]
metaos-agentkit uninstall --global --provider codex,claude [--apply]
```

## Limitations

- Codex and Claude Code may evolve their instruction/skill discovery conventions. Treat this as a small compatibility adapter, and verify the generated files after upgrades.
- The tool does not automatically configure MCP server permissions, Docker mounts, sandbox settings, Claude hooks, OAuth, or secret storage. Those must remain explicit runtime controls.
- Do not set broad permissions such as unrestricted filesystem or network access just because MetaOS rules are present.

## Development

```bash
uv run pytest -q
uv run python -m metaos_agentkit --help
```
