# Capability Profiles

A capability profile is the maximum authority a provider adapter may materialize for one MetaOS `AgentSession`.

It is not a prompt convention. It is validated by the core runtime before launch, recorded in the session asset, and rendered into provider-specific runtime controls.

## Dimensions remain separate

```text
risk          = inherent impact (R0–R4)
mode          = requested action class (observe/propose/stage/commit)
gate          = runtime MetaOS decision (green/yellow/red)
confirmation  = explicit human response for a pending yellow decision
profile       = maximum provider capability materialized for this session
```

A profile never overrides a red gate. A session that fails profile validation is persisted as a blocked red session for auditability.

## Built-in profiles

| Profile | Risk / mode | Provider controls | MCP policy | Isolation |
|---|---|---|---|---|
| `core` | R0–R1, observe/propose | Codex read-only; Claude plan mode | none | none |
| `repo-read` | R1, observe/propose | read-only | none | none |
| `research-read` | R1, observe/propose | read-only, no default network | explicit named read-only servers only | none |
| `repo-stage` | R2, stage | workspace-write + approval request | none | detached Git worktree |
| `external-commit` | R3–R4, commit | workspace-write + approval request | explicit named servers only | no automatic worktree; requires Gate/confirmation |

The profile is selected by `metaos-agentkit task new --profile ...` or inferred from risk and mode.

## Provider translation

### Codex

AgentKit renders session-specific command arguments:

- working directory is the isolated worktree for `repo-stage`;
- sandbox is selected from the resolved profile;
- approval policy is selected from the resolved profile;
- workspace network access is set to the profile value;
- discovered MCP servers not explicitly allowed by the session are disabled with session command overrides;
- pass-through flags that could weaken the boundary (`--sandbox`, `--ask-for-approval`, `--config`, `--add-dir`, bypass flags) are rejected.

### Claude Code

AgentKit writes a session-local `claude-settings.json` that includes:

- sandbox enabled with `failIfUnavailable`;
- write access restricted to the session workspace;
- original checkout made non-writable when a stage worktree is used;
- secret-path read denies;
- empty allowed network domains by default;
- deny entries for MCP servers outside the session allowlist;
- a PreToolUse hook that checks session existence, Gate state, mode, workspace path, shell mutation, and MCP server allowlist.

## MCP policy

MCP is deny-by-default. A task must request an exact server name:

```bash
metaos-agentkit task new "Read official documentation" \
  --risk R1 --mode observe \
  --profile research-read \
  --allow-mcp web-reader
```

The request is still subject to Profile validation and MetaOS Gate evaluation. An MCP server name in a task does not create a connection, supply a token, or grant provider permission outside the configured provider runtime.

## R2 stage worktree

`repo-stage` creates a detached worktree under:

```text
~/.metaos/agentkit/worktrees/<repository-hash>/<session-id>/
```

It starts at the repository `HEAD`; existing uncommitted changes in the user's checkout are not copied. AgentKit records the worktree path in the session launch audit. The resulting process still requires explicit `task finalize` with validation evidence.

## Operational constraints

- Provider settings and hooks are session projections; the canonical truth remains in `SEngine`, `DLayer`, `Decision`, and Trace.
- A provider exit code does not finalize a session.
- Docker socket / mount policy has not yet been wired into a profile. Do not expose Docker socket or broad host mounts through AgentKit until a dedicated container executor is added.
- Profiles do not replace operating-system ACLs, provider managed policy, key storage, OAuth scopes, or sandbox availability checks.
