# AGENTS.md — MetaOS Development Guide

> L2 编排引擎 · 决策门控 + 免疫监控 + 工作流引擎 + MCP 服务

## Quick Commands

```bash
cd projects/metaos

# 测试 (100% 通过, 188 tests)
uv run pytest tests/ -q

# 单个测试
uv run pytest tests/test_workflow_engine.py -q
uv run pytest tests/test_unit.py -q

# 场景测试
uv run pytest tests/ -k "scenario" -q

# 集成测试
uv run pytest tests/integration/ -v

# 语法检查
uv run ruff check src/
uv run ruff format --check src/

# 可直接运行
python3 src/metaos/metaos.py interactive
```

## Architecture

### 核心模块

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| CLI | `cli/__init__.py` | 355 | 14 子命令 + REPL 交互 |
| MCP | `mcp_server.py` | 479 | 11 tools, stdio JSON-RPC |
| SEngine | `core/engine.py` | 515 | 六步编排核心 |
| Workflow | `core/workflow.py` | 297 | DAG 执行 + 重试 + 超时 |
| Workflow Planner | `core/workflow_planner.py` | 221 | LLM + 模式库双路规划 |
| Workflow Store | `core/workflow_store.py` | 114 | SQLite 持久化 + 断点续跑 |
| Gate | `core/gate.py` | 73 | 决策门控 (外部规则) |
| Router | `core/router.py` | 38 | 任务→模型路由 |
| Immune | `core/immune.py` | 290 | 免疫监控 (提醒/冻结/熔断) |
| Deadlock Detector | `deadlock_detector.py` | 363 | 死锁检测 |
| L2 Controller | `l2_controller.py` | 317 | PID 控制器 |
| Types | `core/types.py` | 298 | DecisionLevel/ImmuneLevel/TaskType |
| M Layer | `layers/m_layer.py` | 458 | LLM 适配 (Ollama/OpenAI/Mock) |
| D Layer | `layers/d_layer.py` | 434 | 数字资产 (SQLite + FS) |
| A2A | `a2a/task_manager.py` | 249 | Agent-to-Agent 协议 |
| Cognitive Framework | `core/cognitive_framework.py` | 63 | 动态加载认知 persona |
| Governance | `layers/governance.py` | 292 | 元治理 |
| Community | `layers/community.py` | 344 | 群体场景 |
| Scenarios | `scenarios/` | 901 | 8 个白盒验证场景 |

### 数据流

```
CLI → metaos.py / metaos_main.py
        ↓
   cli/__init__.py (dispatch)
        ↓
   core/engine.py (SEngine 六步)
    ├── core/gate.py    (决策门控)
    ├── core/router.py  (路由)
    ├── layers/m_layer.py (LLM 执行)
    ├── core/immune.py  (免疫检查)
    └── layers/d_layer.py (结果存储)
```

## Key Dependencies

- **fastmcp** — MCP stdio 服务端
- **structlog** — 结构化日志
- **pyyaml** — 配置文件解析
- **runtime 依赖** — metaos 通常由 Agora Mesh 调用，需 runtime 环境

## Testing

```bash
# 全量
uv run pytest tests/ -q

# 核心模块测试
uv run pytest tests/test_unit.py -q          # 单元测试
uv run pytest tests/test_workflow_engine.py -q  # 工作流引擎
uv run pytest tests/test_workflow_mvp.py -q      # 工作流 MVP
uv run pytest tests/test_deadlock_detector.py -q  # 死锁检测
uv run pytest tests/test_l2_controller.py -q     # L2 控制器

# 集成/混沌
uv run pytest tests/integration/test_chaos_workflow.py -v
```

## File Organization

- `src/metaos/` — 源码 (24 模块)
- `src/metaos/cli/` — CLI 子命令
- `src/metaos/core/` — 核心引擎 (engine/gate/immune/router/workflow)
- `src/metaos/layers/` — 执行层 (M 层/D 层/model/governance/community)
- `src/metaos/a2a/` — A2A 协议
- `src/metaos/scenarios/` — 8 个白盒场景
- `src/metaos/config/` — 外部化规则配置
- `tests/` — 单元测试 (5 文件)
- `tests/integration/` — 集成测试 (1 文件)

## Gotchas

1. **Python 3.13+** — 与 kairon 同级，非 runtime 的 3.10+
2. **双 CLI 入口** — `metaos.py`(独立) 和 `metaos_main.py`(pip)，功能等价，修改需同步
3. **规则外部化** — 门控/路由规则在 `config/` 目录，不要在代码中硬编码
4. **认知框架路径** — 从 L0 `ecos/src/ecos/ssot/mof/m1/cognitive_framework/` 动态加载
5. **Workflow 状态在 SQLite** — `workflow_store.py`，断点续跑依赖此文件
6. **Ollama 后端需本地实例** — M 层测试中 MockBackend 用于降级场景


## Bus foundation (跨仓依赖)

本项目通过 `metaos_bus_adapter.py` 接入 [bus-foundation](https://github.com/starlink-awaken/omostation/tree/main/projects/bus-foundation) (R66 独立仓):

```python
from bus_foundation import publish, subscribe, schedule, BusEnvelope
```

- **Public API**: `publish` / `subscribe` / `schedule` / `BusEnvelope` / `EventType`
- **零 agora 依赖**: bus-foundation 是 standalone Python package
- **公共 API 冻结 6 月** (从 2026-06-12 起)
- **L0 协议层提升**: 评估 R70-R72, 决策 **Path C: Defer Indefinitely** (见 `projects/bus-foundation/docs/ADR-0003-no-l0-promotion.md`)
- **修改 bus-foundation**: 提 PR 到 `projects/bus-foundation/`, 改完跑该项目的 `uv run pytest -q` 验证

> 不要直接 import `agora.bus` (那是 backward-compat shim)。新代码用 `from bus_foundation import ...`。
