"""MetaOS Workflow Engine — DAG 编排引擎

特性 (Phase 35 完整版):
- Gap #1: SQLite 状态持久化与断点续跑
- Gap #2: Human-in-the-Loop RED 门控（广播 SSE 事件）
- Gap #4: threading 并行执行无依赖节点
- Gap #8: 每节点指数退避重试策略
- Gap #12: 每节点独立超时保护
"""

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from metaos.core.engine import SEngine
from metaos.core.types import Task
from metaos.core.workflow_store import WorkflowStore
import requests

logger = logging.getLogger("metaos.workflow")

_store = WorkflowStore()  # 全局单例


@dataclass
class WorkflowNode:
    node_id: str
    task_type: str
    input_prompt: str
    depends_on: List[str] = field(default_factory=list)
    output: Optional[str] = None
    status: str = "pending"          # pending | running | completed | failed | timed_out | awaiting_approval
    max_retries: int = 1             # Gap #8: 最大重试次数
    retry_count: int = 0
    timeout_seconds: int = 120       # Gap #12: 节点超时（秒）


class Workflow:
    def __init__(self, workflow_id: str, engine: SEngine):
        self.workflow_id = workflow_id
        self.engine = engine
        self.nodes: Dict[str, WorkflowNode] = {}

    def add_node(self, node: WorkflowNode):
        self.nodes[node.node_id] = node

    def _get_executable_nodes(self) -> List[WorkflowNode]:
        """返回所有依赖已满足且状态为 pending 的节点"""
        return [
            node for node in self.nodes.values()
            if node.status == "pending"
            and all(self.nodes[dep].status == "completed" for dep in node.depends_on)
        ]

    # ── Main Execution Loop ────────────────────────────────────────────────

    def run(self, task_description: str = "", dag_dict: dict | None = None):
        """执行工作流 DAG。集成持久化/并行/重试/超时/人工介入。"""
        logger.info(f"Starting workflow {self.workflow_id} with {len(self.nodes)} nodes.")

        # Gap #1: 持久化工作流启动状态
        _store.save_workflow(self.workflow_id, task_description, dag_dict or {})

        while True:
            executable = self._get_executable_nodes()
            if not executable:
                pending = [n for n in self.nodes.values() if n.status == "pending"]
                running = [n for n in self.nodes.values() if n.status == "running"]
                if not pending and not running:
                    logger.info("Workflow completed successfully.")
                    _store.complete_workflow(self.workflow_id, "completed")
                    break
                elif not running and pending:
                    logger.error("Workflow deadlocked. Unresolved dependencies.")
                    _store.complete_workflow(self.workflow_id, "deadlocked")
                    break
                else:
                    time.sleep(0.5)
                    continue

            # Gap #4: 并行执行所有当前可执行节点
            threads = []
            stop_event = threading.Event()

            for node in executable:
                node.status = "running"
                t = threading.Thread(
                    target=self._execute_node,
                    args=(node, stop_event),
                    daemon=True
                )
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            if stop_event.is_set():
                _store.complete_workflow(self.workflow_id, "stopped")
                return

    # ── Node Execution ─────────────────────────────────────────────────────

    def _execute_node(self, node: WorkflowNode, stop_event: threading.Event):
        """在独立线程中执行单个节点，支持重试和超时。"""
        context = ""
        if node.depends_on:
            context = "\n【上游依赖结果】\n"
            for dep in node.depends_on:
                context += f"[{dep}]: {self.nodes[dep].output}\n"

        task_input = node.input_prompt + context
        task = Task(
            task_id=f"{self.workflow_id}_{node.node_id}",
            h_id="metaos",
            task_type=node.task_type,
            input=task_input
        )

        # Gap #8: 重试循环（指数退避）
        while node.retry_count <= node.max_retries:
            success = self._try_execute(node, task, task_input, stop_event)
            if success or stop_event.is_set():
                break
            node.retry_count += 1
            if node.retry_count <= node.max_retries:
                wait = 2 ** node.retry_count
                logger.warning(f"Node {node.node_id} retry {node.retry_count}/{node.max_retries} in {wait}s")
                time.sleep(wait)

        # Gap #1: checkpoint 写入 DB
        _store.update_node(
            self.workflow_id, node.node_id, node.task_type,
            node.input_prompt, node.depends_on, node.status, node.output or ""
        )

    def _try_execute(self, node: WorkflowNode, task: Task, task_input: str,
                     stop_event: threading.Event) -> bool:
        """尝试执行节点一次，返回是否成功。"""
        if node.task_type == "research":
            return self._execute_research(node, task_input)
        else:
            return self._execute_engine(node, task, stop_event)

    def _execute_research(self, node: WorkflowNode, task_input: str) -> bool:
        """委托给 Cockpit Research Agent 执行（含超时）"""
        logger.info(f"Delegating {node.node_id} to Cockpit Research Agent...")
        result: dict = {"returncode": -1, "stdout": "", "stderr": ""}

        def _run():
            try:
                r = subprocess.run(
                    ["uv", "run", "--directory", "projects/cockpit", "cockpit",
                     "research", task_input[:200]],
                    capture_output=True, text=True, check=False,
                    timeout=node.timeout_seconds
                )
                result.update({"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
            except subprocess.TimeoutExpired:
                result["stderr"] = "subprocess timeout"

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=node.timeout_seconds + 5)

        if t.is_alive() or result["returncode"] == -1:
            # Gap #12: 超时
            node.status = "timed_out"
            node.output = f"[超时] Cockpit research 超过 {node.timeout_seconds}s"
            self._publish_event(node)
            return False

        if result["returncode"] == 0:
            node.output = result["stdout"]
            node.status = "completed"
            self._publish_event(node)
            return True

        node.output = result["stderr"]
        node.status = "failed"
        self._publish_event(node)
        return False

    def _execute_engine(self, node: WorkflowNode, task: Task,
                        stop_event: threading.Event) -> bool:
        """通过 SEngine 执行节点（含超时和 RED 门控处理）"""
        result_holder: list = [None]

        def _call():
            result_holder[0] = self.engine.process(task)

        # Gap #12: 超时保护
        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=node.timeout_seconds)

        if t.is_alive():
            node.status = "timed_out"
            node.output = f"[超时] SEngine 超过 {node.timeout_seconds}s"
            self._publish_event(node)
            return False

        result = result_holder[0] or {}

        if result.get("status") in ("completed", "logged"):
            node.output = result.get("output", "")
            node.status = "completed"
            self._publish_event(node)
            return True

        if result.get("status") == "pending_h":
            # Gap #2: Human-in-the-Loop — 暂停工作流，广播审批事件
            logger.warning(f"Node {node.node_id} hit RED gate — awaiting human approval.")
            node.status = "awaiting_approval"
            node.output = result.get("message", "需要人工审批")
            self._publish_human_approval_event(node)
            stop_event.set()
            return False

        node.status = "failed"
        node.output = str(result)
        self._publish_event(node)
        return False

    # ── SSE Publishing ─────────────────────────────────────────────────────

    def _publish_event(self, node: WorkflowNode):
        """发布节点状态 SSE 事件到 Agora 网格"""
        try:
            requests.post(
                "http://127.0.0.1:8080/v1/events",
                json={
                    "source": "metaos_workflow",
                    "target": node.task_type,
                    "event_type": f"node_{node.status}",
                    "payload": {
                        "workflow_id": self.workflow_id,
                        "node_id": node.node_id,
                        "status": node.status,
                    }
                },
                headers={"Authorization": "Bearer omo_core_token"},
                timeout=2
            )
        except Exception as e:
            logger.warning(f"SSE publish failed for {node.node_id}: {e}")

    def _publish_human_approval_event(self, node: WorkflowNode):
        """Gap #2: 广播 human_approval_required 事件，等待人工介入"""
        try:
            requests.post(
                "http://127.0.0.1:8080/v1/events",
                json={
                    "source": "metaos_workflow",
                    "target": "human",
                    "event_type": "human_approval_required",
                    "payload": {
                        "workflow_id": self.workflow_id,
                        "node_id": node.node_id,
                        "reason": node.output,
                        "approve_cmd": f"metaos approve {self.workflow_id}",
                    }
                },
                headers={"Authorization": "Bearer omo_core_token"},
                timeout=2
            )
        except Exception as e:
            logger.warning(f"Failed to publish approval event: {e}")
