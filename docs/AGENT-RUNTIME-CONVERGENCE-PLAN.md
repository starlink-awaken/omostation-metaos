# Agent Runtime Convergence Plan

## Phase A — completed in this change

- Canonical `AgentSession` contract.
- Separation of operational risk, execution mode, gate outcome, and lifecycle status.
- `AgentRuntimeService.prepare/finalize` connected to `DecisionGate`, `DLayer`, `Decision`, and Trace.
- `metaos-agent` CLI bridge.
- Provider context projection that grants no additional authority.

## Phase B — next change

- Move AgentKit's session creation from legacy task-envelope JSON to `metaos-agent prepare`.
- Have AgentKit reject provider execution when the prepared session is blocked.
- Write provider-local session files only as projections of canonical assets.
- Implement explicit `metaos-agent finalize` handoff after provider result collection.

## Phase C — enforcement

- Map capability profiles to Codex sandbox/approval configuration.
- Map capability profiles to Claude Code permissions/hooks.
- Map allowed MCP servers/tools and Docker mounts from the same profile.
- Add adapter contract tests against installed provider versions.

## Non-goals

- Prompt text is not treated as a security boundary.
- AgentKit does not become a second workflow engine.
- Provider adapters do not own decision logging, approval, long-term memory, or audit truth.
