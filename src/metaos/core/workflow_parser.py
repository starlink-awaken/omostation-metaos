import logging
from pathlib import Path
from typing import Any

import yaml

from metaos.core.engine import SEngine
from metaos.core.workflow import Workflow, WorkflowNode

logger = logging.getLogger("metaos.workflow_parser")

class WorkflowParser:
    """Parses a YAML definition into an executable MetaOS Workflow."""

    def __init__(self, engine: SEngine):
        self.engine = engine

    def parse_file(self, file_path: str | Path) -> Workflow:
        """Parse a YAML file into a Workflow."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return self.parse_dict(data)

    def parse_dict(self, data: dict[str, Any]) -> Workflow:
        """Parse a dictionary into a Workflow."""
        if "workflow_id" not in data:
            raise ValueError("Missing 'workflow_id' in definition.")

        workflow_id = data["workflow_id"]
        logger.info(f"Parsing workflow: {workflow_id} ({data.get('name', 'Unnamed')})")

        workflow = Workflow(workflow_id=workflow_id, engine=self.engine)

        nodes = data.get("nodes", [])
        for n in nodes:
            node_id = n.get("id")
            if not node_id:
                raise ValueError(f"Node missing 'id': {n}")

            task_type = n.get("type", "general")
            prompt = n.get("prompt", "")
            depends_on = n.get("depends_on", [])

            node = WorkflowNode(
                node_id=node_id,
                task_type=task_type,
                input_prompt=prompt,
                depends_on=depends_on
            )
            workflow.add_node(node)

        # 校验环依赖等图结构（TODO: 暂时简单实现）
        self._validate_dag(workflow)

        return workflow

    def _validate_dag(self, workflow: Workflow):
        """简单的 DAG 校验，确保所有依赖都在图内，且没有自环"""
        for node_id, node in workflow.nodes.items():
            for dep in node.depends_on:
                if dep not in workflow.nodes:
                    raise ValueError(f"Node {node_id} depends on unknown node {dep}")
                if dep == node_id:
                    raise ValueError(f"Node {node_id} has a self-dependency")
