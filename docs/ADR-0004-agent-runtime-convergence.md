# ADR-0004: Agent Runtime Convergence

- **Status:** Accepted
- **Date:** 2026-06-28

## Context

MetaOS already owns the governance path for tasks: `SEngine → DecisionGate → Router → MLayer → ImmuneMonitor → DLayer/Trace`. The first AgentKit prototype created provider instruction files, task JSON, and launcher context directly. That made it useful as a personal CLI bootstrapper but left a parallel task model, state path, and audit path outside MetaOS.

## Decision

Provider integrations must use `metaos.integrations.agent_runtime` as the canonical boundary.

1. `AgentSession` is the provider-neutral contract.
2. Operational risk (`R0`–`R4`), execution mode, and MetaOS gate result are independent dimensions.
3. The MetaOS core is the system of record for session state, decisions, assets, and traces.
4. Provider adapters may project a session into local files, environment variables, native instruction files, skills, or launch commands, but may not decide authorization or synthesize successful completion.
5. The `metaos-agent prepare` and `metaos-agent finalize` commands are the initial bridge for external adapters.
6. Provider-local task files are projections/caches only. They must be reconstructible from the canonical session asset.

## Consequences

- AgentKit remains a thin, user-friendly provider adapter rather than a second orchestration runtime.
- R0–R4 does not replace green/yellow/red: the first describes impact, while the second is the live gate outcome.
- R3/R4 commits may be blocked by yellow/red gates even when a provider is otherwise available.
- MCP permissions, sandboxing, hooks, OAuth, Docker mounts, and secret handling remain enforcement responsibilities outside prompt text.

## Migration

`tools/metaos-agentkit` should migrate its task creation and launch lifecycle to call this bridge. Its legacy `task-envelope.json` format is deprecated in favor of the `AgentSession` projection format.
