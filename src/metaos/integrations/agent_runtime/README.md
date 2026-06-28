# Agent Runtime Integration

This package is the single contract boundary between MetaOS governance and provider-specific command-line adapters.

## Contract dimensions

| Dimension | Owner | Meaning |
|---|---|---|
| `risk` (`R0`–`R4`) | User/task declaration | inherent operation impact |
| `mode` | Adapter invocation | maximum execution authority |
| `gate_decision` | MetaOS `DecisionGate` | dynamic authorization outcome |
| `status` | MetaOS session lifecycle | prepared, blocked, running, finalized, failed, cancelled |

These dimensions must not be conflated. A task can be `R2 + stage + green`, or `R3 + commit + yellow`. In the second case the provider may be prepared but must not execute until the MetaOS confirmation path approves it.

## Ownership

- `SEngine`, `DecisionGate`, `ImmuneMonitor`, `DLayer`, and Trace remain the governance system of record.
- Provider adapters may create files, provider instruction blocks, or launch commands, but must use a prepared `AgentSession` and report completion through `finalize`.
- Task/session records are represented as `DigitalAsset` entries and linked to a `Decision` plus trace events. Provider-specific files are only projections of that canonical state.
