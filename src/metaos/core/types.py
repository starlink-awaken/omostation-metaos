"""核心数据类型——本体模型完整代码映射（v3.1 SSOT: 01-理论基础/05-本体模型.md）"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# ═══════════════════════════════════════════
# 值类型：枚举
# ═══════════════════════════════════════════


class DecisionLevel(StrEnum):
    """决策级别（本体决策级别 DecisionLevel）"""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class ImmuneLevel(StrEnum):
    """免疫级别（本体免疫级别 ImmuneLevel）"""

    NONE = "none"
    WARNING = "warning"
    FREEZE = "freeze"
    MELTDOWN = "meltdown"


class TaskType(StrEnum):
    """任务类型"""

    INFO_RETRIEVAL = "info_retrieval"
    REASONING = "reasoning"
    CODE_GEN = "code_gen"
    DOMAIN_ANALYSIS = "domain_analysis"
    MULTIMODAL = "multimodal"
    MORNING_RITUAL = "morning_ritual"
    EVENING_REVIEW = "evening_review"
    MICRO_REVIEW = "micro_review"


class AssetLevel(StrEnum):
    """资产层级（本体 D_私有 / D_共有 / D_融合）"""

    PRIVATE = "private"
    SHARED = "shared"
    FUSED = "fused"


class ModelType(StrEnum):
    """模型专长类型（本体 M.type）"""

    GENERAL = "general"
    REASONING = "reasoning"
    CODE = "code"
    DOMAIN = "domain"
    MULTIMODAL = "multimodal"


class CouplingRule(StrEnum):
    """耦合协议子类（本体 S 的子协议）"""

    COGNITIVE_CIRCUIT = "cognitive_circuit"
    DECISION_GATE = "decision_gate"
    IMMUNE_MECHANISM = "immune_mechanism"
    ASSET_TRACE = "asset_trace"
    COMMUNITY_PROTOCOL = "community_protocol"


# ═══════════════════════════════════════════
# 核心实体：HumanSubject (H)
# ═══════════════════════════════════════════


@dataclass
class H:
    """HumanSubject——存在性主体（会痛一侧）

    本体属性：id, maturity, decision_history, privilege_list
    本体关系：produces(H,D), delegates(H,M), confirms(H,Decision), carries(H,Consequence)
    公理：不可数字化、不可合并、不可复制，责任的唯一载体
    """

    h_id: str
    name: str = ""
    maturity: float = 0.5  # 内核成熟度 [0,1]
    privilege_list: list[str] = field(default_factory=lambda: ["green"])  # 当前权限级别
    decision_history: list[str] = field(default_factory=list)  # 决策链记录
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired

    def __post_init__(self):
        if isinstance(self.privilege_list, list) and not self.privilege_list:
            self.privilege_list = ["green"]


# ═══════════════════════════════════════════
# 核心实体：DigitalAsset (D)
# ═══════════════════════════════════════════


@dataclass
class DigitalAsset:
    """DigitalAsset——数字资产

    本体属性：id, level, source_H, auth_timestamp, revision_log,
             dependency_list, rollback_snapshot, privacy_level
    本体关系：authored_by(D,H), used_in(D,Decision), trains(D_fused,M)
    约束：D_私有→D_共有 必须经 H 显式授权，不可逆
    """

    asset_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    level: AssetLevel = AssetLevel.PRIVATE
    content: str = ""
    summary: str = ""
    source_h_id: str = ""  # 源头主体（本体 source_H）
    asset_type: str = "text"  # text / code / image / audio / structured
    tags: list[str] = field(default_factory=list)

    # 溯源链（本体 auth_timestamp, revision_log, dependency_list）
    auth_timestamp: datetime | None = None
    revision_log: list[dict] = field(default_factory=list)
    dependency_list: list[str] = field(default_factory=list)
    verification_count: int = 0
    challenge_count: int = 0
    rollback_snapshot_uri: str = ""
    privacy_level: float = 0.5  # 本体 privacy_level [0,1]

    # 验证质量
    verification_h_ids: set = field(default_factory=set)
    first_verified: datetime | None = None
    last_verified: datetime | None = None
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# ═══════════════════════════════════════════
# 核心实体：Decision（本体产物，非独立实体）
# ═══════════════════════════════════════════


@dataclass
class Decision:
    """决策日志条目——映射本体 Decision 类型"""

    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    h_id: str = ""
    level: str = "green"
    action: str = ""  # approved / rejected / modified
    description: str = ""
    assets_used: list[str] = field(default_factory=list)
    immune_triggered: str = "none"
    timestamp: datetime = field(default_factory=datetime.now)
    outcome_pending_review: bool = True
    review_deadline: datetime | None = None
    access_level: str = "owner"  # owner / shared / public
    api_version: str = "1.0"
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# ═══════════════════════════════════════════
# 核心实体：Principle（认知流转产物）
# ═══════════════════════════════════════════


@dataclass
class Principle:
    """原则——来自认知流转的经验教训提炼"""

    principle_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    content: str = ""
    source_h_id: str = ""
    source_experience: str = ""
    applicability_tags: list[str] = field(default_factory=list)
    verification_count: int = 0
    conflict_principles: list[str] = field(default_factory=list)
    status: str = "active"  # active / disputed / deprecated
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# ═══════════════════════════════════════════
# 运行时数据：Task & TaskResult（S↔M 协议）
# ═══════════════════════════════════════════


@dataclass
class Task:
    """S→M 任务派发"""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    h_id: str = ""
    task_type: str = ""
    input: str = ""
    context_asset_ids: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


@dataclass
class TaskResult:
    """M→S 结果返回"""

    task_id: str = ""
    status: str = "completed"
    output: str = ""
    confidence: float = 0.7
    assets_used: list[str] = field(default_factory=list)
    reasoning_chain: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# ═══════════════════════════════════════════
# 模型能力（映射本体 Capability 维度 CAP01-CAP07）
# ═══════════════════════════════════════════


@dataclass
class CapabilityMap:
    """模型能力评分（本体 Capability 维度表 CAP01-CAP07）"""

    reasoning_depth: int = 5  # CAP01: 推理深度 1-10
    knowledge_breadth: int = 5  # CAP02: 知识广度 1-10
    instruction_following: int = 5  # CAP03: 指令遵循 1-10
    context_window: int = 32000  # CAP04: 上下文窗口
    response_speed_ms: dict = field(default_factory=lambda: {"p50": 1000, "p95": 3000})
    cost_per_1k_tokens: float = 0.003  # CAP06: 成本
    domain_specificity: dict = field(default_factory=dict)  # CAP07: 领域特化度
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# ═══════════════════════════════════════════
# 模型引擎：ModelEngine (M)
# ═══════════════════════════════════════════


@dataclass
class ModelConfig:
    """模型注册配置——映射本体 ModelEngine

    本体属性：id, type, capability_map, api_endpoint, cost_profile, fused_assets
    """

    model_id: str
    model_type: str  # general / reasoning / code / domain / multimodal
    endpoint: str = "mock://"  # 本体 api_endpoint
    capability: CapabilityMap = field(default_factory=CapabilityMap)  # 本体 capability_map
    healthy: bool = True
    cost_usd_per_1k: float = 0.0  # 本体 cost_profile
    fused_asset_ids: list[str] = field(default_factory=list)  # 本体 fused_assets
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired


# ═══════════════════════════════════════════
# 耦合协议：CouplingProtocol (S)
# ═══════════════════════════════════════════


@dataclass
class SProtocol:
    """耦合协议——本体 CouplingProtocol (S)

    子协议：
    - CognitiveCircuit: 认知流转规则
    - DecisionGate: 权限门控规则（engine/gate.py）
    - ImmuneMechanism: 免疫机制规则（engine/immune.py）
    - AssetTrace: 资产溯源规则（layer/d_layer.py）
    - CommunityProtocol: 社区协议（layer/community.py）
    """

    rule_id: str = ""
    rule_type: CouplingRule = CouplingRule.COGNITIVE_CIRCUIT
    content: str = ""
    enabled: bool = True
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime | None = None
    value_tier: int = 0  # 0=unknown, 1-7 matching X3 tiers
    half_life_days: int = 365  # default 1 year
    freshness_status: str = "fresh"  # fresh | aging | stale | expired
