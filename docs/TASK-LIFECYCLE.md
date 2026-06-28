# AgentKit Task Lifecycle

AgentKit task directories are provider-local projections. MetaOS Core remains the canonical source of truth for Gate, approval, session state, decisions, assets, and trace records.

## Task selection

List tasks before acting when more than one task is active:

```bash
metaos-agentkit task list
metaos-agentkit task list --all
```

Use an explicit task id for lifecycle operations:

```bash
metaos-agentkit task approve --task task-20260628T120000Z-a1b2c3d4
metaos-agentkit launch codex --task task-20260628T120000Z-a1b2c3d4 --execute
metaos-agentkit task finalize --task task-20260628T120000Z-a1b2c3d4 \
  --summary "Focused tests passed" \
  --evidence "pytest tests/auth -q" \
  --verification-passed
```

When exactly one low-risk active task exists, `--task` may be omitted. When multiple active tasks exist, AgentKit refuses to guess. R3/R4 `commit` tasks always require `--task` explicitly.

## High-risk external commit binding

R3/R4 commit tasks require an exact target binding, verification expectation, and a short expiry:

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
```

The runtime validates the binding at `prepare`. A yellow Gate approval records a target fingerprint. Before provider launch, MetaOS validates that the target has not changed and that the binding has not expired.

## MCP declarations

MCP is deny-by-default.

```bash
# Whole-server request, retained for compatibility:
--allow-mcp docs

# Preferred least-privilege request:
--allow-mcp calendar:create_event
```

Claude Code enforces exact server/tool rules in the MetaOS PreToolUse hook. Codex disables non-allowed servers and prompts for every tool of an allowed server; Codex does not yet have an equivalent per-tool deny projection, so use tool-specific requests as approval intent rather than assuming an OS-grade tool filter.

## Evidence and finalization

AgentKit captures a bounded evidence bundle before `finalize` containing:

- launch-plan and provider-exit file SHA-256 values;
- detached worktree path, HEAD, status, `git diff --stat`, and `git diff --check` results when available;
- a finalization timestamp.

The bundle is persisted into the canonical session asset. Provider exit code alone never marks a session successful; `--verification-passed` remains an explicit assertion that the recorded verification evidence supports success.

## Archival and cleanup

Terminal tasks can be archived without deleting the canonical MetaOS asset:

```bash
# Preview
metaos-agentkit task archive --task task-... 

# Move the local projection and remove its MetaOS-managed worktree
metaos-agentkit task archive --task task-... --apply

# Archive terminal tasks older than 14 days
metaos-agentkit task cleanup --older-than 14 --apply
```

Archival only removes a worktree under `~/.metaos/agentkit/worktrees/`. It refuses to delete worktrees outside that managed root.
