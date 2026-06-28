# Governed Provider Session Flow

```text
Provider request
  → AgentSession (risk + mode + capability profile)
  → metaos-agent prepare
      → DecisionGate
      → Decision / DigitalAsset / Trace
      → prepared or blocked
  → provider-specific projection and launch
  → verification collection
  → metaos-agent finalize
      → canonical outcome asset + trace + immune observation
```

A provider adapter must refuse launch when `prepare` returns a blocked session. A successful process exit is not success; only `finalize --verification-passed` records a finalized session.
