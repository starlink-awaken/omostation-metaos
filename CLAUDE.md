# CLAUDE.md — MetaOS 编排引擎

> L2 编排引擎 · 决策门控 + 免疫监控 + 工作流引擎 + MCP 服务

---


## 项目身份

metaos 是 eCOS v6 5+4+1+1 架构的 L2 引擎面一员。2026-06-06 从 `projects/kairon/packages/metaos` 拆出为独立项目。

**核心职责**：
1. **决策门控** (DecisionGate) — 红/黄/绿灯语义安全判定
2. **免疫监控** (ImmuneMonitor) — 三层机制 (提醒→冻结→熔断)
3. **工作流引擎** — DAG 编排、并行执行、SQLite 断点续跑
4. **认知框架** — 动态加载 BDSK/Six Hats 等框架 persona
5. **MCP 服务** — 11 个工具暴露给 Agora Mesh

---

## 架构

### 六步决策路径 (SEngine)

```
1. DecisionGate → 2. Router → 3. MLayer → 4. ImmuneMonitor → 5. 结果组装 → 6. H确认
```

### 模块层级

| 层 | 模块 | 文件 | 职责 |
|----|------|------|------|
| **入口** | CLI | `cli/__init__.py` | 14 子命令 + REPL |
| | MCP | `mcp_server.py` | 11 tools, stdio |
| **编排** | SEngine | `core/engine.py` | 核心编排 (515 行) |
| | Workflow | `core/workflow.py` | DAG 执行引擎 |
| | Planner | `core/workflow_planner.py` | LLM + 模式库双路规划 |
| **门控** | Gate | `core/gate.py` | 决策门控 (外部规则) |
| | Router | `core/router.py` | 路由决策 (外部规则) |
| **免疫** | Immune | `core/immune.py` | 提醒/冻结/熔断 + 语义噪声 |
| | Deadlock | `deadlock_detector.py` | 死锁检测 |
| | L2 Controller | `l2_controller.py` | L2 PID 控制器 |
| **执行** | M Layer | `layers/m_layer.py` | LLM 适配 (Ollama/OpenAI/Mock) |
| | D Layer | `layers/d_layer.py` | 数字资产存储 (SQLite + FS) |
| | A2A | `a2a/task_manager.py` | Agent-to-Agent 协议 |
| **场景** | Scenarios | `scenarios/` | 8 个白盒场景测试 |

---

## 快速命令

```bash
cd projects/metaos

# 测试 (100% 通过)
uv run pytest tests/ -q

# 场景验证
python3 -m metaos.run scenario_id

# 启动向导
metaos onboard

# 仪表盘
metaos dashboard

# MCP Server
metaos-mcp
```

---

## CLI 命令清单

| 命令 | 触发场景 |
|------|---------|
| `metaos register <h_id>` | 首次注册 |
| `metaos morning [text]` | 晨间仪式 |
| `metaos evening [text]` | 晚间整合 |
| `metaos review <action> <expected> <actual>` | 微粒复盘 |
| `metaos gate <text>` | 决策门控 |
| `metaos status` | 体系健康度 |
| `metaos trace` | 决策日志 |
| `metaos day <1-7>` | 启动指南日课 |
| `metaos ssot` | SSOT 覆盖扫描 |
| `metaos onboard` | 交互式向导 |
| `metaos dashboard` | HTML 仪表盘 |
| `metaos-mcp` | MCP stdio 服务 |

---

## 数据类型约定

- `DecisionLevel` — GREEN (放行) / YELLOW (警告) / RED (阻止)
- `ImmuneLevel` — NONE / WARNING / FREEZE (超阈值只读) / MELTDOWN (核心价值观冲突)
- `TaskType` — INFO_RETRIEVAL / REASONING / CODE_GEN / DOMAIN_ANALYSIS / MULTIMODAL 等

---

## GPTCHAS

1. **规则外部化** — 门控规则在 `config/decision_matrix.json`，路由规则在 `config/task_routes.json`，支持热重载
2. **Python 3.13+** — 与 kairon 同级要求
3. **hatchling 构建** — 与 kairon/agora 一致，与 runtime 的 setuptools 不同
4. **Workflow 断点续跑** — workflow_store.py 用 SQLite 持久化状态，中断后可恢复
5. **认知框架动态加载** — 从 L0 MOF 模型 `ecos/src/ecos/ssot/mof/m1/cognitive_framework/` 加载
6. **双 CLI 入口** — `metaos.py`(独立运行) 和 `metaos_main.py`(pip 安装后)，两个入口功能等价
7. **Ollama 需要本地运行** — M 层 Ollama 后端依赖本地 ollama 实例
