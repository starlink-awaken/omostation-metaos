# metaos — System Boundary

> 本文档描述 metaos 与 eCOS 系统其他部分的边界：暴露的接口、依赖的上游、影响的下游。
>
> 系统全景参见：[`../../docs/PANORAMA.md`](../../docs/PANORAMA.md)

---

## 0. 职责边界 (CONV-3, 2026-08-24)

> **治理执行 (omo) vs 编排决策 (metaos)** — 防双轨 drift 的职责划分契约。
> 登记: CONV-3 决策 (用户授权), ADR (能力级, docs/.omo/_knowledge/decisions)。

| 维度 | omo (治理执行) | metaos (编排决策) |
|------|----------------|-------------------|
| 定位 | 治理内核: schema/audit/sync/broker/lint | L2 编排引擎: 决策门控/免疫/路由/工作流 |
| 决策 | 判定"是否符合治理规则" (合规事实) | 决定"下一步做什么" (编排选择) |
| 状态 | 治理状态平面 (governance-data, system.yaml) | 编排状态 (workflow store, immune levels) |
| 门控 | 治理门禁 (gac-local-gate, MOF schema) | 决策门控 (core/gate.py, 外部规则) |
| 免疫 | 治理漂移检测/修复 | 运行时免疫 (提醒/冻结/熔断) |
| 路由 | BOS URI 域路由 (bos://governance/*) | 任务→模型路由 (core/router.py) |

**接口契约**:
- metaos 不得绕过 omo 直接写 `.omo/_truth` 治理状态 (治理执行面归 omo)。
- metaos 的决策输入可消费 omo 治理事实 (governance-data), 但输出为编排决策, 不修改治理规则。
- omo 不实现编排决策 (工作流选择/免疫策略) — 那是 metaos 职责。
- 重叠检测: 若新需求同时涉及"治理规则判定"与"编排选择", 分别归 omo / metaos, 登记为契约点。

## 1. 暴露接口

### BOS URI

- `bos://governance/metaos/decide`
- `bos://governance/metaos/immune`
- `bos://governance/metaos/route`
- `bos://governance/metaos/gate`
- `bos://governance/metaos/register`

### 入口

- **CLI**: `metaos` 子命令 (见 project-registry.yaml: metaos) + REPL
- **MCP stdio**: `python -m metaos.mcp_server` MCP tools (见 project-registry.yaml: metaos)
- **Dashboard**: `metaos dashboard` 

## 2. 上游依赖

- agora (I0)
- ecos (L0)
- omo (L2 governance)

## 3. 下游影响

- runtime
- kairon

## 4. 配置 / SSOT

- 项目源码：`projects/metaos/`
- 入口定义：`projects/metaos/pyproject.toml` 或 `package.json`
- 测试：`cd projects/metaos && uv run pytest tests/ -q`

## 架构演进与项目边界索引

参见工作区架构演进与项目边界：[`../../docs/ARCHITECTURE-EVOLUTION.md`](../../docs/ARCHITECTURE-EVOLUTION.md)
