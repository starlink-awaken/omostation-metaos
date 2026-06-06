"""
MetaOS Workflow Planner — 动态工作流生成器

给定一个自然语言任务描述，自动分析任务结构，
生成 DAG 节点计划，并返回可立即执行的 Workflow 对象。

架构：
1. LLM-based Planner: 向 Ollama 发送结构化 prompt，要求返回 JSON DAG
2. Heuristic Fallback: 基于关键词匹配的模式库，离线降级
3. WorkflowParser: 复用已有解析器将 dict → Workflow
"""

import json
import logging
import re
from typing import Any

from metaos.core.engine import SEngine
from metaos.core.workflow import Workflow
from metaos.core.workflow_parser import WorkflowParser

logger = logging.getLogger("metaos.workflow_planner")


# ─── Heuristic Task Templates ────────────────────────────────────────────────

TASK_PATTERNS = [
    {
        "keywords": ["研究", "research", "调研", "了解", "分析"],
        "template": [
            {"id": "gather", "type": "research", "prompt": "围绕以下主题收集信息：{task}"},
            {"id": "analyze", "type": "reasoning", "prompt": "分析以下收集到的信息，提炼 3 个关键发现：{task}", "depends_on": ["gather"]},
            {"id": "report", "type": "reasoning", "prompt": "基于以上分析，生成一份简洁的研究报告（含摘要、发现、建议）：{task}", "depends_on": ["analyze"]},
        ]
    },
    {
        "keywords": ["写", "撰写", "起草", "draft", "write", "文章", "报告", "文档"],
        "template": [
            {"id": "outline", "type": "reasoning", "prompt": "为以下写作任务制定详细大纲：{task}"},
            {"id": "draft", "type": "reasoning", "prompt": "根据大纲撰写正文：{task}", "depends_on": ["outline"]},
            {"id": "review", "type": "reasoning", "prompt": "审查并优化以下内容，提出具体改进建议：{task}", "depends_on": ["draft"]},
        ]
    },
    {
        "keywords": ["代码", "实现", "开发", "code", "implement", "develop", "编写"],
        "template": [
            {"id": "design", "type": "reasoning", "prompt": "设计以下功能的技术方案（接口、数据结构、核心逻辑）：{task}"},
            {"id": "implement", "type": "code_gen", "prompt": "根据设计方案实现代码：{task}", "depends_on": ["design"]},
            {"id": "test", "type": "reasoning", "prompt": "为以下代码生成测试用例和验收标准：{task}", "depends_on": ["implement"]},
        ]
    },
    {
        "keywords": ["规划", "计划", "plan", "roadmap", "路线图", "方案"],
        "template": [
            {"id": "situation", "type": "info_retrieval", "prompt": "分析当前现状和背景：{task}"},
            {"id": "options", "type": "reasoning", "prompt": "列举 3 个可选方案及其优缺点：{task}", "depends_on": ["situation"]},
            {"id": "plan", "type": "reasoning", "prompt": "综合以上选项，制定最终行动计划（含时间节点和关键里程碑）：{task}", "depends_on": ["options"]},
        ]
    },
    {
        "keywords": ["总结", "汇总", "summarize", "归纳", "梳理"],
        "template": [
            {"id": "collect", "type": "info_retrieval", "prompt": "收集相关信息：{task}"},
            {"id": "summarize", "type": "reasoning", "prompt": "对收集到的内容进行结构化总结：{task}", "depends_on": ["collect"]},
        ]
    },
]

DEFAULT_TEMPLATE = [
    {"id": "understand", "type": "reasoning", "prompt": "理解并拆解以下任务的核心目标和约束：{task}"},
    {"id": "execute", "type": "reasoning", "prompt": "执行以下任务并输出结果：{task}", "depends_on": ["understand"]},
]


# ─── LLM-based Planner ───────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """\
你是一个任务拆解专家。给定用户的任务描述，你需要将其分解为一个有向无环图（DAG）工作流。

可用的节点类型：
- research: 调用外部 Agent 搜索和收集信息
- reasoning: 调用推理引擎进行分析、总结、规划
- code_gen: 生成代码
- info_retrieval: 检索结构化数据

规则：
1. 节点数量控制在 2-5 个
2. 每个节点必须有唯一的 id（英文小写+下划线）
3. depends_on 必须引用已存在的节点 id
4. prompt 必须具体描述该节点要做什么，包含原始任务的关键内容

你的输出必须是合法的 JSON 格式，包含 workflow_id 和 nodes 字段，绝对不要输出其他内容。

示例输出：
{
  "workflow_id": "research_rag_2024",
  "name": "RAG 架构研究",
  "nodes": [
    {"id": "gather", "type": "research", "prompt": "搜集 RAG 架构的最新进展和最佳实践"},
    {"id": "analyze", "type": "reasoning", "prompt": "分析 RAG 与 Fine-tuning 的对比优势", "depends_on": ["gather"]},
    {"id": "report", "type": "reasoning", "prompt": "输出一份 RAG 技术选型建议报告", "depends_on": ["analyze"]}
  ]
}
"""


class WorkflowPlanner:
    """动态工作流规划器：自然语言任务 → 可执行 Workflow"""

    def __init__(self, engine: SEngine, use_llm: bool = True):
        self.engine = engine
        self.use_llm = use_llm
        self._parser = WorkflowParser(engine)

    def plan(self, task: str, auto_run: bool = False) -> Workflow:
        """
        根据任务描述生成工作流。
        
        Args:
            task: 自然语言任务描述
            auto_run: 是否生成后立即执行
            
        Returns:
            一个已配置好的 Workflow 对象
        """
        print(f"\n🧠 MetaOS Planner 分析任务中...")
        print(f"   任务: {task[:80]}")

        dag_dict = None

        # 1. 尝试 LLM 规划
        if self.use_llm:
            dag_dict = self._plan_with_llm(task)

        # 2. Fallback: 启发式规划
        if dag_dict is None:
            print("   ⚡️ 使用启发式模板规划...")
            dag_dict = self._plan_with_heuristics(task)

        print(f"   ✅ 规划完成: {len(dag_dict['nodes'])} 个节点")

        wf = self._parser.parse_dict(dag_dict)
        return wf

    def _plan_with_llm(self, task: str) -> dict[str, Any] | None:
        """尝试使用 Ollama LLM 生成 DAG"""
        try:
            import requests
            # 优先选择支持 chat 的模型（跳过 gemma4，它不支持）
            preferred_models = ["qwen3.5:4b", "qwen3.5:9b", "fredrezones55/Qwopus3.5:9b"]
            model = self._pick_working_model(preferred_models)
            if not model:
                return None

            print(f"   🤖 调用 LLM ({model}) 生成规划...")
            r = requests.post(
                "http://localhost:11434/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                        {"role": "user", "content": f"请为以下任务生成工作流 DAG：\n{task}"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                    "stream": False,
                },
                timeout=60,
            )

            if r.status_code != 200:
                logger.warning(f"LLM planner failed: HTTP {r.status_code}")
                return None

            msg = r.json()["choices"][0]["message"]
            # qwen3.5 把推理过程放在 reasoning 字段，content 可能为空
            # 优先从 content 取，content 为空则从 reasoning 中提取 JSON
            content = msg.get("content", "").strip()
            reasoning = msg.get("reasoning", "").strip()

            result = self._extract_json(content) if content else None
            if result is None and reasoning:
                result = self._extract_json(reasoning)

            return result

        except Exception as e:
            logger.warning(f"LLM planning failed: {e}")
            return None

    def _pick_working_model(self, candidates: list[str]) -> str | None:
        """选出一个实际可用（支持 chat）的 Ollama 模型"""
        try:
            import requests
            r = requests.get("http://localhost:11434/api/tags", timeout=5)
            available = {m["name"] for m in r.json().get("models", [])}
            for c in candidates:
                for a in available:
                    if a.startswith(c.split(":")[0]):
                        # 快速验证 chat 接口
                        test = requests.post(
                            "http://localhost:11434/v1/chat/completions",
                            json={"model": a, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5, "stream": False},
                            timeout=30,
                        )
                        if test.status_code == 200:
                            return a
        except Exception:
            pass
        return None

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        """从 LLM 输出中提取 JSON（兼容 markdown 代码块和 qwen3.5 <think> 标签）"""
        # 1. 剥离 <think>...</think> 推理过程（qwen 模型特有）
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

        # 2. 尝试直接解析
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # 3. 从 ```json...``` 代码块提取
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 4. 找第一个完整的 { ... } 块
        match = re.search(r"\{[\s\S]+\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to extract JSON from LLM output: {text[:200]}")
        return None

    def _plan_with_heuristics(self, task: str) -> dict[str, Any]:
        """基于关键词匹配生成启发式 DAG"""
        task_lower = task.lower()

        for pattern in TASK_PATTERNS:
            if any(kw in task_lower for kw in pattern["keywords"]):
                template = pattern["template"]
                nodes = [
                    {
                        **n,
                        "prompt": n["prompt"].format(task=task),
                    }
                    for n in template
                ]
                workflow_id = re.sub(r"\W+", "_", task[:30].strip()).lower()
                return {
                    "workflow_id": workflow_id or "auto_workflow",
                    "name": task[:50],
                    "nodes": nodes,
                }

        # 完全无法匹配，使用兜底模板
        nodes = [
            {**n, "prompt": n["prompt"].format(task=task)}
            for n in DEFAULT_TEMPLATE
        ]
        return {
            "workflow_id": "generic_task",
            "name": task[:50],
            "nodes": nodes,
        }
