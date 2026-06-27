# Agent Runtime Convergence Plan

## Phase A — completed

- Canonical `AgentSession` contract.
- Separation of operational risk, execution mode, Gate outcome, confirmation, and lifecycle status.
- `AgentRuntimeService.prepare/finalize` connected to `DecisionGate`, `DLayer`, `Decision`, and Trace.
- `metaos-agent` CLI bridge.
- Provider context projection that grants no additional authority.

## Phase B — completed

- AgentKit session creation uses the canonical AgentSession shape rather than legacy task-envelope JSON.
- AgentKit refuses Provider execution for blocked sessions.
- Provider-local files are projections; canonical session state is persisted as a MetaOS asset.
- Explicit `metaos-agent finalize` handoff records verification evidence after Provider work.
- `metaos-agent context` and canonical asset loading prevent lifecycle transitions from trusting altered local projections.

## Phase C — completed baseline

- Capability profiles are validated by the MetaOS runtime before Gate execution.
- Codex receives session-scoped sandbox, approval, workspace network, MCP-disable, and protected-argument controls.
- Claude Code receives a generated session settings overlay, sandbox constraints, secret-path denies, MCP deny entries, and a PreToolUse capability hook.
- R2 and high-risk stage profiles use detached Git worktrees so uncommitted user files are not copied into the Agent workspace.
- Explicit MCP requests are deny-by-default and subject to Profile validation.
- Adapter smoke tests and a GitHub Actions workflow validate the standalone AgentKit package.

## Phase D — remaining enforcement work

- Add a dedicated container executor before exposing Docker socket, Docker mounts, or container-management MCP tools.
- Add provider-version smoke tests against the locally installed Codex and Claude Code versions.
- Add OS-level path ACL validation where supported by the host platform.
- Add canonical session integrity signatures or database-backed optimistic version checks for multi-process concurrency.
- Move capability profile configuration into a user-editable, schema-validated policy file once the built-ins stabilize.

## Non-goals

- Prompt text is not treated as a security boundary.
- AgentKit does not become a second workflow engine.
- Provider adapters do not own decision logging, approval, long-term memory, or audit truth.
