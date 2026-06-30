# metaos — Architecture

> **Layer**: L2 引擎面  
> **Role**: 编排引擎 — 决策门控 / 免疫监控 / 路由 / 工作流  
> **Stack**: Python 3.13+, uv, fastmcp, structlog  
> **Health**: See local CI and runtime probes
> **SSOT**: 运行时健康、测试通过率、入口/工具计数以本项目 CI、运行时探针和 workspace governance SSOT 为准
>
> 系统全景参见：[`../../docs/PANORAMA.md`](../../docs/PANORAMA.md)

---

## 1. 内部架构

```mermaid

graph TB
    Req[Request]
    Gate[Decision Gate]
    Immune[Immune Monitor]
    Engine[SEngine]
    WF[Workflow DAG]
    LLM[M Layer LLM]
    DB[(SQLite)]

    Req --> Gate
    Gate -->|GREEN| Immune
    Immune -->|OK| Engine
    Engine --> WF
    Engine --> LLM
    WF --> DB

```

## 2. 入口

| Type | Entry | Port / Notes |
|:--|:--|:--|
| CLI | `metaos` | 子命令 (见 project-registry.yaml: metaos) + REPL |
| MCP stdio | `python -m metaos.mcp_server` | MCP tools (见 project-registry.yaml: metaos) |
| Dashboard | `metaos dashboard` |  |

## 3. 核心模块

| Module | Responsibility |
|:--|:--|
| `src/metaos/core/engine.py` | SEngine six-step orchestration |
| `src/metaos/core/gate.py` | Decision gate GREEN/YELLOW/RED |
| `src/metaos/core/immune.py` | Immune monitor WARNING/FREEZE/MELTDOWN |
| `src/metaos/core/workflow.py` | DAG workflow engine |
| `src/metaos/mcp_server.py` | MCP server |
| `src/metaos/layers/m_layer.py` | LLM adapter |

## 4. 测试

```bash
cd projects/metaos && uv run pytest tests/ -q
```
