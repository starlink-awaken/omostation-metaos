# MetaOS

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Contributing](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Security](https://img.shields.io/badge/security-policy-blue.svg)](SECURITY.md)
[![Python](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-package%20manager-purple.svg)](https://docs.astral.sh/uv/)

> 独立项目 · 从 omostation kairon monorepo 拆出 (P30-W1-METAOS-EXTRACT, 2026-06-06)
> 架构归属: L2 编排引擎 (见 `.omo/_knowledge/management/architecture-final-state-v3.md`)

决策门控、免疫监控、路由、数字资产引擎。

## 职责

- 决策门控 (decision gate)
- 免疫监控 (immune)
- 路由 (router)
- 层管理 (m_layer / d_layer / governance / community)
- MCP stdio 服务 (多 session 隔离)
- 死锁检测 (deadlock detector)
- 仪表盘 (dashboard)

## 快速开始

```bash
uv sync
uv run python -c "import metaos; print(metaos.__version__)"
uv run pytest tests/ -v
```

## CLI

```bash
metaos --help                  # 查看所有命令
metaos status                  # 体系健康度
metaos trace                   # 最近决策日志
metaos gate <decision_desc>    # 决策门控
metaos review <action> <exp> <act>  # 微粒复盘
metaos ssot-scan               # SSOT 覆盖扫描
```

## MCP

```bash
metaos-mcp                     # 启动 MCP stdio 服务 (JSON-RPC)
```

多 session 隔离版，每个 MCP 连接使用独立 H + token。

## 依赖关系

- **被依赖**: 0（自包含）
- **依赖**: fastmcp, structlog

## 迁移历史

- **2026-06-06** 从 `projects/kairon/packages/metaos` 拆出 (P30-W1 METAOS-EXTRACT)
  - 源码 ~3,453 行 (14 modules, 5 sub-modules)
  - 测试 1,611 行
  - git 历史: 通过 `git mv` 至 kairon `_staging` 中转, 然后物理迁出 (保留 rename 检测)
  - 7.1.0 → 0.1.0 (独立项目, 重新计版本)

## 包结构

```
metaos/
├── pyproject.toml
├── README.md
├── src/metaos/
│   ├── __init__.py
│   ├── metaos.py            # 核心
│   ├── metaos_main.py       # 主入口
│   ├── mcp_server.py        # MCP stdio
│   ├── l2_controller.py     # L2 控制器
│   ├── deadlock_detector.py # 死锁检测
│   ├── dashboard.py         # 仪表盘
│   ├── onboard.py           # 引导
│   ├── run.py               # 运行
│   ├── cli/                 # CLI 实现
│   ├── core/                # 核心 (engine/gate/immune/router/types)
│   ├── layers/              # 层 (m/d/governance/community)
│   ├── scenarios/           # 场景测试
│   └── config/              # 配置
└── tests/
    ├── test_deadlock_detector.py
    ├── test_l2_controller.py
    └── test_unit.py
```
## Project Governance

- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [License](LICENSE)
- [Code of Conduct](CODE_OF_CONDUCT.md)