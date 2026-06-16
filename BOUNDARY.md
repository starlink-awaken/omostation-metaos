# metaos — System Boundary

> 本文档描述 metaos 与 eCOS 系统其他部分的边界：暴露的接口、依赖的上游、影响的下游。
>
> 架构演进对比参见：[`docs/ARCHITECTURE-EVOLUTION.md`](../docs/ARCHITECTURE-EVOLUTION.md)

---

## 1. 暴露接口

### BOS URI

- `bos://governance/metaos/decide`
- `bos://governance/metaos/immune`
- `bos://governance/metaos/route`
- `bos://governance/metaos/gate`
- `bos://governance/metaos/register`

### 入口

- **CLI**: `metaos` 14 子命令 + REPL
- **MCP stdio**: `python -m metaos.mcp_server` 11 tools
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
