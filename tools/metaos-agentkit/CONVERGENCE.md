# AgentKit Convergence Status

`metaos-agentkit` is a provider adapter, not an orchestration runtime.

## Current rule

For governed runs, create a canonical `AgentSession` through the root MetaOS bridge:

```bash
metaos-agent prepare --session-file input.json --out prepared.json
# Launch Codex or Claude Code only when prepared.json is not blocked.
metaos-agent finalize --session-file prepared.json --out final.json \
  --summary "..." --evidence "..." --verification-passed
```

The `.metaos/` files created by AgentKit are provider-local projections and cache/working state. Canonical authorization, decisions, assets, traces, and lifecycle state belong to root MetaOS.

## Migration target

AgentKit v0.2 will call this bridge automatically and treat a blocked session as a hard launch refusal. It must not make an independent green/yellow/red decision or store a parallel source of truth.
