"""MetaOS Workflow Engine — DAG 编排引擎

特性 (Phase 35 完整版):
- Gap #1: SQLite 状态持久化与断点续跑
- Gap #2: Human-in-the-Loop RED 门控（广播 SSE 事件）
- Gap #4: threading 并行执行无依赖节点
- Gap #8: 每节点指数退避重试策略
- Gap #12: 每节点独立超时保护
"""

import asyncio
import logging
from dataclasses import dataclass, field

import requests

from metaos.core.engine import SEngine
from metaos.core.types import Task
from metaos.core.workflow_store import WorkflowStore

logger = logging.getLogger("metaos.workflow")

_store = WorkflowStore()  # 全局单例


@dataclass
class WorkflowNode:
    node_id: str
    task_type: str
    input_prompt: str
    depends_on: list[str] = field(default_factory=list)
    output: str | None = None
    status: str = "pending"          # pending | running | completed | failed | timed_out | awaiting_approval
    max_retries: int = 1             # Gap #8: 最大重试次数
    retry_count: int = 0
    timeout_seconds: int = 120       # Gap #12: 节点超时（秒）


class Workflow:
    def __init__(self, workflow_id: str, engine: SEngine):
        self.workflow_id = workflow_id
        self.engine = engine
        self.nodes: dict[str, WorkflowNode] = {}

    def add_node(self, node: WorkflowNode):
        self.nodes[node.node_id] = node

    def _get_executable_nodes(self) -> list[WorkflowNode]:
        """返回所有依赖已满足且状态为 pending 的节点"""
        return [
            node for node in self.nodes.values()
            if node.status == "pending"
            and all(self.nodes[dep].status == "completed" for dep in node.depends_on)
        ]

    # ── Main Execution Loop ────────────────────────────────────────────────

    async def run(self, task_description: str = "", dag_dict: dict | None = None):
        """执行工作流 DAG。集成持久化/并行/重试/超时/人工介入。"""
        import asyncio
        logger.info(f"Starting workflow {self.workflow_id} with {len(self.nodes)} nodes.")

        # Gap #1: 持久化工作流启动状态
        _store.save_workflow(self.workflow_id, task_description, dag_dict or {})

        stop_event = asyncio.Event()
        node_tasks: dict[str, asyncio.Task] = {}

        while True:
            if stop_event.is_set():
                _store.complete_workflow(self.workflow_id, "stopped")
                if node_tasks:
                    await asyncio.gather(*node_tasks.values(), return_exceptions=True)
                return

            executable = self._get_executable_nodes()
            pending = [n for n in self.nodes.values() if n.status == "pending"]
            running = [n for n in self.nodes.values() if n.status == "running"]

            if not pending and not running and not executable:
                logger.info("Workflow completed successfully.")
                _store.complete_workflow(self.workflow_id, "completed")
                break
            elif not running and pending and not executable:
                logger.error("Workflow deadlocked or cascaded failure. Unresolved dependencies.")
                _store.complete_workflow(self.workflow_id, "deadlocked")
                break

            # Gap #4: 并发执行所有当前可执行节点
            for node in executable:
                node.status = "running"
                task = asyncio.create_task(self._execute_node(node, stop_event))
                node_tasks[node.node_id] = task

            if node_tasks:
                done, _ = await asyncio.wait(
                    node_tasks.values(), return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    # Remove finished task from tracking map
                    for nid, ntask in list(node_tasks.items()):
                        if ntask == t:
                            del node_tasks[nid]
                            # Cascade failure if needed
                            if self.nodes[nid].status in ("failed", "timed_out"):
                                logger.error(f"Node {nid} failed. Cascading failure to dependents.")
                                self._cascade_fail(nid)
            else:
                await asyncio.sleep(0.5)

    def _cascade_fail(self, failed_node_id: str):
        """级联失败所有依赖此节点的下游节点"""
        for node in self.nodes.values():
            if node.status == "pending" and failed_node_id in node.depends_on:
                node.status = "failed"
                node.output = f"Upstream node {failed_node_id} failed."
                self._publish_event(node)
                self._cascade_fail(node.node_id)

    # ── Node Execution ─────────────────────────────────────────────────────

    async def _execute_node(self, node: WorkflowNode, stop_event: asyncio.Event):
        """在独立 Task 中执行单个节点，支持重试和超时。"""
        import asyncio
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
            if stop_event.is_set():
                break
            success = await self._try_execute(node, task, task_input, stop_event)
            if success or stop_event.is_set():
                break

            node.retry_count += 1
            if node.retry_count <= node.max_retries:
                wait = 2 ** node.retry_count
                logger.warning(f"Node {node.node_id} retry {node.retry_count}/{node.max_retries} in {wait}s")
                await asyncio.sleep(wait)

        # Gap #1: checkpoint 写入 DB
        _store.update_node(
            self.workflow_id, node.node_id, node.task_type,
            node.input_prompt, node.depends_on, node.status, node.output or ""
        )

    async def _try_execute(self, node: WorkflowNode, task: Task, task_input: str,
                     stop_event: asyncio.Event) -> bool:
        """尝试执行节点一次，返回是否成功。"""
        if node.task_type == "research":
            return await self._execute_research(node, task_input)
        else:
            return await self._execute_engine(node, task, stop_event)

    async def _execute_research(self, node: WorkflowNode, task_input: str) -> bool:
        """委托给 Cockpit Research Agent 执行（含超时）"""
        import asyncio
        logger.info(f"Delegating {node.node_id} to Cockpit Research Agent...")

        try:
            proc = await asyncio.create_subprocess_exec(
                "uv", "run", "--directory", "projects/cockpit", "cockpit",
                "research", task_input[:200],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=node.timeout_seconds)
                returncode = proc.returncode
            except TimeoutError:
                proc.kill()
                node.status = "timed_out"
                node.output = f"[超时] Cockpit research 超过 {node.timeout_seconds}s"
                self._publish_event(node)
                return False

            if returncode == 0:
                node.output = stdout.decode('utf-8')
                node.status = "completed"
                self._publish_event(node)
                return True

            node.output = stderr.decode('utf-8')
            node.status = "failed"
            self._publish_event(node)
            return False

        except Exception as e:
            node.output = f"Research subprocess failed: {e}"
            node.status = "failed"
            self._publish_event(node)
            return False

    async def _execute_engine(self, node: WorkflowNode, task: Task,
                        stop_event: asyncio.Event) -> bool:
        """通过 SEngine 执行节点（含超时和 RED 门控处理）"""
        import asyncio

        def _call_engine():
            return self.engine.process(task)

        try:
            # Use to_thread so SEngine.process doesn't block the async loop
            result = await asyncio.wait_for(asyncio.to_thread(_call_engine), timeout=node.timeout_seconds)
        except TimeoutError:
            node.status = "timed_out"
            node.output = f"[超时] SEngine 超过 {node.timeout_seconds}s"
            self._publish_event(node)
            return False
        except Exception as e:
            node.status = "failed"
            node.output = str(e)
            self._publish_event(node)
            return False

        result = result or {}

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
