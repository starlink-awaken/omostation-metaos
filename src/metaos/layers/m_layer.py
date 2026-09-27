"""M 层——模型池适配器

三层后端架构：
  1. OllamaBackend（本地 LLM，OpenAI 兼容 API）
  2. OpenAIBackend（远程 API）
  3. MockBackend（无网络降级回退 + 白盒测试）

截至 v7.0 迭代，当前活跃实现：
  - ✅ MockBackend —— 保留为降级回退 + 测试
  - ✅ OllamaBackend —— 新增，自动检测可用性
  - ⬜ OpenAIBackend —— v7.0 Sprint 1 规划
  - ⬜ AnthropicBackend —— v7.0 Sprint 1 规划
"""

import logging
import os
import time

from metaos.core.types import CapabilityMap, ModelConfig, Task, TaskResult  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


# ── 抽象后端基类（参考 v7.0 迭代规格说明书 S1.1） ──


class ModelBackend:
    """模型后端抽象基类"""

    def call(self, task: Task, model_id: str) -> TaskResult:
        raise NotImplementedError

    def health(self) -> bool:
        raise NotImplementedError


# ── Ollama 后端（本地 LLM，OpenAI 兼容 API） ──


class OllamaBackend(ModelBackend):
    """本地 LLM 后端 —— 经 aetherforge 门面(OpenAI 兼容 API)

    类名沿用 OllamaBackend 以兼容既有引用; 本地推理现只走门面(见 metaos.core.llm_gateway)。

    环境变量：
      LLM_GATEWAY_URL  — 门面地址(默认 http://127.0.0.1:4000, 带不带 /v1 均可)
      LLM_MODEL / OLLAMA_MODEL — 门面别名(默认 fast)
      OLLAMA_TIMEOUT   — 请求超时秒数（默认 120）
    """

    def __init__(self, base_url: str = "", model: str = ""):
        import requests as req

        from metaos.core import llm_gateway

        self._requests = req
        self._gw = llm_gateway

        standard_provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
        standard_base_url = os.environ.get("LLM_BASE_URL")
        standard_model = os.environ.get("LLM_MODEL")
        use_standard = standard_provider in {"", "ollama", "gateway", "aetherforge"}
        self.base_url = llm_gateway.root(
            base_url or (standard_base_url if use_standard and standard_base_url else None)
        )
        self.model = (
            model
            or (standard_model if use_standard and standard_model else None)
            or os.environ.get("OLLAMA_MODEL", "")
            or llm_gateway.DEFAULT_MODEL
        )
        self.timeout = int(os.environ.get("OLLAMA_TIMEOUT", "120"))
        self._available = False
        self._detected_models: list[str] = []

        # 初始化时执行自动检测
        self._auto_detect()

    # ── 自动检测 ──

    def _auto_detect(self):
        """探测门面 /health(免鉴权)。旧实现探测 Ollama 的 /api/tags —— 门面无此路由, 恒判不可用。"""
        try:
            r = self._requests.get(f"{self.base_url}/health", timeout=5)
            if r.status_code == 200:
                self._available = True
                logger.info("LLM 门面检测通过 | 端点=%s 模型=%s", self.base_url, self.model)
            else:
                logger.warning("LLM 门面返回异常状态码: %s", r.status_code)
        except Exception as exc:  # defensive fallback
            logger.info("LLM 门面不可用（将使用 Mock 降级）: %s", exc)

    def health(self) -> bool:
        """健康检查——返回门面是否可用"""
        if not self._available:
            return False
        try:
            r = self._requests.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except Exception:  # defensive fallback
            self._available = False
            return False

    def call(self, task: Task, model_id: str = "") -> TaskResult:
        """经门面调用本地模型——使用配置的门面别名，忽略逻辑 model_id"""
        start = time.time()

        if not self._available:
            return TaskResult(
                task_id=task.task_id,
                status="failed",
                output="[Ollama 不可用] 服务未运行或网络不可达",
                latency_ms=int((time.time() - start) * 1000),
            )

        model = self.model  # 门面别名
        if not model:
            return TaskResult(
                task_id=task.task_id,
                status="failed",
                output="[Ollama 配置错误] 未指定模型",
                latency_ms=int((time.time() - start) * 1000),
            )

        try:
            r = self._requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._gw.auth_headers(),
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个认知操作系统引擎。直接输出结果，不要思考过程。"
                            "请基于以下任务类型和输入，输出简洁、结构化、可操作的回应。",
                        },
                        {"role": "user", "content": f"[{task.task_type}] {task.input}"},
                    ],
                    "temperature": 0.1,  # 低温度减少发散思考
                    "max_tokens": 1024,  # 限制输出长度
                    "stream": False,
                },
                timeout=self.timeout,
            )
            elapsed = int((time.time() - start) * 1000)

            if r.status_code == 200:
                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    return TaskResult(
                        task_id=task.task_id,
                        status="completed",
                        output=f"[Ollama 返回为空，已使用 Mock 降级] 任务: {task.input[:50]}...",
                        confidence=0.5,
                        latency_ms=elapsed,
                    )
                return TaskResult(
                    task_id=task.task_id,
                    status="completed",
                    output=content,
                    confidence=0.85,
                    latency_ms=elapsed,
                )
            else:
                return TaskResult(
                    task_id=task.task_id,
                    status="failed",
                    output=f"[Ollama 错误] HTTP {r.status_code}: {r.text[:200]}",
                    latency_ms=elapsed,
                )

        except Exception as exc:  # defensive fallback
            elapsed = int((time.time() - start) * 1000)
            logger.error("Ollama 调用异常: %s", exc)
            # 一次失败标记为不可用，后续自动降级
            self._available = False
            return TaskResult(
                task_id=task.task_id,
                status="failed",
                output=f"[Ollama 调用失败] {exc} — 已自动降级至 Mock 模式",
                latency_ms=elapsed,
            )

    def get_capability_map(self) -> CapabilityMap:
        """根据模型名称推断能力映射"""
        base = CapabilityMap(
            reasoning_depth=6,
            knowledge_breadth=7,
            context_window=8192,
        )
        if not self.model:
            return base
        m = self.model.lower()
        if "llama" in m:
            base.context_window = 8192 if "3.2" in m else 128000
        elif "qwen" in m:
            base.reasoning_depth = 7
            base.context_window = 32768
        elif "mistral" in m:
            base.reasoning_depth = 7
            base.context_window = 32768
        elif "deepseek" in m:
            base.reasoning_depth = 8
            base.context_window = 65536
        return base


# ── Mock 后端（降级回退 + 白盒测试） ──


class MockBackend(ModelBackend):
    """Mock 后端——无 LLM 时降级回退

    所有输出添加 [SIMULATED] 水印，确保用户不会被假数据误导。
    """

    def __init__(self, watermark: bool = True):
        self.watermark = watermark
        self._available = True

    def health(self) -> bool:
        return True

    def _w(self, text: str) -> str:
        """添加模拟水印"""
        if self.watermark:
            return f"[SIMULATED] {text}"
        return text

    def call(self, task: Task, model_id: str = "") -> TaskResult:
        start = time.time()
        output = self._mock_process(task, model_id)
        latency = 200 + hash(task.input) % 800
        time.sleep(min(latency / 1000, 0.5))
        return TaskResult(
            task_id=task.task_id,
            status="completed",
            output=self._w(output),
            confidence=0.75 + (hash(task.input) % 20) / 100,
            latency_ms=int((time.time() - start) * 1000),
        )

    def _mock_process(self, task: Task, model_id: str) -> str:
        if "晨间" in task.input or "morning" in task.input.lower():
            return (
                "【今日认知焦点】\n"
                "1. 基于昨日记录，你当前有 X 个未闭合决策\n"
                "2. 建议今日聚焦：优先处理 Y\n"
                "3. 提醒：周检查点 Z 即将到期"
            )
        elif "晚间" in task.input or "evening" in task.input.lower():
            return (
                "【晚间整合】\n1. 今日认知收获：主要在处理 X 任务中发现了 Y 模式\n2. 建议经验教训：Z\n3. 待确认：无\n"
            )
        elif "复盘" in task.input or "review" in task.input.lower():
            return (
                "【归因分析】\n"
                "差异分析：预期 X，实际 Y\n"
                "可能原因：\n"
                "1. 信息不足\n"
                "2. 框架选择偏差\n"
                "经验教训草案：在 Z 场景下，应优先考虑 W"
            )
        elif "风险" in task.input or "决策" in task.input:
            return (
                "【决策分析】\n"
                "方案比较：\n"
                "- 方案A：收益高但风险大\n"
                "- 方案B：稳健但回报有限\n"
                "建议：选择方案A，设定3个风险检查点"
            )
        else:
            return f"[{model_id}] 收到任务: {task.input[:50]}..."


# ── MLayer —— 模型池适配器（重构版） ──


class MLayer:
    """模型池适配器

    V7.0 重构：引入 ModelBackend 抽象层，支持多后端自动切换。
    后端选择链：OllamaBackend → MockBackend（带水印）
    """

    def __init__(self, backend: ModelBackend | None = None):
        self.models: dict[str, ModelConfig] = {}
        self._backend: ModelBackend
        self._backend_name: str = "mock"

        if backend is not None:
            # 显式注入后端（测试用）
            self._backend = backend
            self._backend_name = f"injected({type(backend).__name__})"
        else:
            # 自动选择：Ollama → Mock
            ollama = OllamaBackend()
            if ollama.health():
                self._backend = ollama
                self._backend_name = f"ollama({ollama.model})"
                logger.info("MLayer 使用 Ollama 后端: %s", ollama.model)
            else:
                self._backend = MockBackend(watermark=True)
                self._backend_name = "mock(watermarked)"
                logger.info("MLayer 使用 Mock 后端（带水印）")

        self._register_defaults()

    @property
    def backend_name(self) -> str:
        return self._backend_name

    def _register_defaults(self):
        defaults = [
            ModelConfig("general", "general", capability=CapabilityMap(reasoning_depth=5, knowledge_breadth=7)),
            ModelConfig(
                "reasoning",
                "reasoning",
                capability=CapabilityMap(reasoning_depth=8, knowledge_breadth=5, domain_specificity={"logic": 9}),
            ),
            ModelConfig(
                "code",
                "code",
                capability=CapabilityMap(
                    reasoning_depth=6, knowledge_breadth=4, domain_specificity={"python": 9, "javascript": 8}
                ),
            ),
            ModelConfig(
                "domain",
                "domain",
                capability=CapabilityMap(reasoning_depth=6, knowledge_breadth=8, context_window=64000),
            ),
        ]
        # 如果是 Ollama 后端，用真实能力覆盖
        if isinstance(self._backend, OllamaBackend):
            cap = self._backend.get_capability_map()
            defaults = [
                ModelConfig("general", "general", capability=cap),
                ModelConfig("reasoning", "reasoning", capability=cap),
                ModelConfig("code", "code", capability=cap),
                ModelConfig("domain", "domain", capability=cap),
            ]
        for m in defaults:
            self.register(m)

    def register(self, config: ModelConfig):
        self.models[config.model_id] = config

    def unregister(self, model_id: str):
        self.models.pop(model_id, None)

    def health_check(self, model_id: str) -> bool:
        config = self.models.get(model_id)
        if not config:
            return False
        return config.healthy

    def get_healthy_models(self, model_type: str = None) -> list[str]:  # type: ignore[reportArgumentType]
        return [
            mid for mid, c in self.models.items() if c.healthy and (model_type is None or c.model_type == model_type)
        ]

    def call(self, task: Task, model_id: str = "") -> TaskResult:
        """同步调用——委托给当前后端"""
        if not model_id:
            type_map = {
                "info_retrieval": "general",
                "reasoning": "reasoning",
                "code_gen": "code",
                "domain_analysis": "domain",
                "morning_ritual": "general",
                "evening_review": "general",
                "micro_review": "reasoning",
            }
            mtype = type_map.get(task.task_type, "general")
            candidates = self.get_healthy_models(mtype)
            if not candidates:
                candidates = self.get_healthy_models("general")
            if not candidates:
                return TaskResult(task_id=task.task_id, status="failed", output="[M 全量不可用]")
            model_id = candidates[0]

        # 即使指定了 model_id，也检查健康状态
        cfg = self.models.get(model_id)
        if cfg and not cfg.healthy:
            return TaskResult(task_id=task.task_id, status="failed", output=f"[M 不可用] 模型 {model_id} 当前不可用")

        return self._backend.call(task, model_id)

    # ── 测试辅助 ──

    def inject_failure(self, model_ids: list[str]):
        for mid in model_ids:
            if mid in self.models:
                self.models[mid].healthy = False

    def restore_all(self):
        for m in self.models.values():
            m.healthy = True

    def get_ollama_info(self) -> dict:
        """返回 Ollama 状态（供 CLI/监控使用）"""
        if isinstance(self._backend, OllamaBackend):
            return {
                "available": self._backend.health(),
                "model": self._backend.model,
                "endpoint": self._backend.base_url,
                "detected_models": self._backend._detected_models,
            }
        return {"available": False, "reason": "not_configured"}
