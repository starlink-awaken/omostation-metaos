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


from pathlib import Path

import yaml


def _load_templates():
    template_path = Path(__file__).parent.parent / "templates" / "workflow_planner.yaml"
    try:
        with open(template_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return (
                data.get("task_patterns", []),
                data.get("default_template", []),
                data.get("system_prompt", "")
            )
    except Exception as e:  # noqa: BLE001  # defensive fallback
        logger.error(f"Failed to load planner templates: {e}")
        return [], [], ""

TASK_PATTERNS, DEFAULT_TEMPLATE, PLANNER_SYSTEM_PROMPT = _load_templates()


class WorkflowPlanner:
    """动态工作流规划器：自然语言任务 → 可执行 Workflow"""

    def __init__(self, engine: SEngine, use_llm: bool = True):
        self.engine = engine
        self.use_llm = use_llm
        self._parser = WorkflowParser(engine)
        self._last_dag: dict = {}  # stores last generated DAG for --save

    def plan(self, task: str, auto_run: bool = False) -> Workflow:
        """
        根据任务描述生成工作流。

        Args:
            task: 自然语言任务描述
            auto_run: 是否生成后立即执行

        Returns:
            一个已配置好的 Workflow 对象
        """
        print("\n🧠 MetaOS Planner 分析任务中...")
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
        self._last_dag = dag_dict  # persist for --save
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

            # Load L4 CARDS context for alignment
            from metaos.core.cards_context import get_cards_context
            from metaos.core.cognitive_framework import CognitiveFrameworkLoader

            l4_context = get_cards_context()
            loader = CognitiveFrameworkLoader()
            cognitive_prompt = loader.build_cognitive_prompt(task)

            system_prompt = PLANNER_SYSTEM_PROMPT + l4_context + cognitive_prompt

            print(f"   🤖 调用 LLM ({model}) 生成规划...")
            r = requests.post(
                "http://localhost:11434/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
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

        except Exception as e:  # noqa: BLE001  # defensive fallback
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
        except Exception:  # noqa: BLE001  # defensive fallback
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

        # 4. 找最外层的 { ... } 块 (非贪婪或从头到尾匹配最后一个})
        match = re.search(r"\{[\s\S]*\}", text)
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
