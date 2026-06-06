import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from metaos.core.types import Task, DecisionLevel
from metaos.core.engine import SEngine
import requests

logger = logging.getLogger("metaos.workflow")

@dataclass
class WorkflowNode:
    node_id: str
    task_type: str  # e.g. "reasoning", "code_gen", "research"
    input_prompt: str
    depends_on: List[str] = field(default_factory=list)
    output: Optional[str] = None
    status: str = "pending"  # pending, running, completed, failed

class Workflow:
    def __init__(self, workflow_id: str, engine: SEngine):
        self.workflow_id = workflow_id
        self.engine = engine
        self.nodes: Dict[str, WorkflowNode] = {}
        
    def add_node(self, node: WorkflowNode):
        self.nodes[node.node_id] = node
        
    def _get_executable_nodes(self) -> List[WorkflowNode]:
        executable = []
        for node in self.nodes.values():
            if node.status == "pending":
                can_run = all(self.nodes[dep].status == "completed" for dep in node.depends_on)
                if can_run:
                    executable.append(node)
        return executable

    def _publish_event(self, node: WorkflowNode):
        """发布 SSE 事件到 Agora 网格"""
        try:
            requests.post(
                "http://127.0.0.1:8080/v1/events",
                json={
                    "source": "metaos_workflow",
                    "target": node.task_type,
                    "event_type": "node_completed",
                    "payload": {
                        "workflow_id": self.workflow_id,
                        "node_id": node.node_id,
                        "status": node.status
                    }
                },
                headers={"Authorization": "Bearer omo_core_token"},
                timeout=2
            )
        except Exception as e:
            logger.warning(f"Failed to publish event for node {node.node_id}: {e}")

    def run(self):
        logger.info(f"Starting workflow {self.workflow_id} with {len(self.nodes)} nodes.")
        
        while True:
            executable = self._get_executable_nodes()
            if not executable:
                # 检查是否全部完成或卡住
                pending = [n for n in self.nodes.values() if n.status == "pending"]
                running = [n for n in self.nodes.values() if n.status == "running"]
                if not pending and not running:
                    logger.info("Workflow completed successfully.")
                    break
                elif not running and pending:
                    logger.error("Workflow deadlocked. Unresolved dependencies.")
                    break
                else:
                    time.sleep(1)
                    continue
            
            for node in executable:
                node.status = "running"
                logger.info(f"Executing node: {node.node_id}")
                
                # 构建带有上游依赖输出的上下文
                context = ""
                if node.depends_on:
                    context = "\n【上游依赖结果】\n"
                    for dep in node.depends_on:
                        context += f"[{dep}]: {self.nodes[dep].output}\n"
                
                task_input = node.input_prompt + context
                task = Task(task_id=f"{self.workflow_id}_{node.node_id}", h_id="metaos", task_type=node.task_type, input=task_input)
                
                # 触发 S 引擎处理（MVP版本先尝试调用Cockpit CLI执行真实任务，降级走SEngine）
                if node.task_type == "research":
                    logger.info(f"Delegating node {node.node_id} to Cockpit Research Agent...")
                    import subprocess
                    try:
                        # 假设使用 cockpit research 执行
                        res = subprocess.run(
                            ["uv", "run", "--directory", "projects/cockpit", "cockpit", "research", task_input],
                            capture_output=True, text=True, check=False
                        )
                        if res.returncode == 0:
                            node.output = res.stdout
                            node.status = "completed"
                            self._publish_event(node)
                        else:
                            node.output = res.stderr
                            node.status = "failed"
                            self._publish_event(node)
                    except Exception as e:
                        logger.error(f"Failed to delegate to Cockpit: {e}")
                        node.status = "failed"
                        self._publish_event(node)
                    continue
                else:
                    result = self.engine.process(task)
                    
                    if result.get("status") == "completed" or result.get("status") == "logged":
                        node.output = result.get("output", "")
                        node.status = "completed"
                        logger.info(f"Node {node.node_id} completed via SEngine.")
                        self._publish_event(node)
                    elif result.get("status") == "pending_h":
                        logger.warning(f"Node {node.node_id} hit RED light, waiting for Human.")
                        node.status = "failed" # 对于全自动编排，需要人工介入等于中断
                        self._publish_event(node)
                        return
                    else:
                        logger.error(f"Node {node.node_id} failed: {result}")
                        node.status = "failed"
                        self._publish_event(node)
                        return
