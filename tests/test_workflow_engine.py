"""Unit tests for MetaOS Workflow Engine (workflow.py, workflow_parser.py, workflow_planner.py)

All tests use Mock backends to avoid Ollama/SQLite dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch
from metaos.core.workflow import Workflow, WorkflowNode
from metaos.core.workflow_parser import WorkflowParser
from metaos.core.workflow_planner import WorkflowPlanner


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_engine():
    """A fully mocked SEngine that auto-authenticates and returns success."""
    engine = MagicMock()
    engine.process.return_value = {"status": "completed", "output": "mock output"}
    engine._h_sessions = {}
    engine._current_h_id = "test_user"
    return engine


@pytest.fixture
def simple_workflow(mock_engine):
    wf = Workflow(workflow_id="test_wf", engine=mock_engine)
    wf.add_node(WorkflowNode(node_id="step1", task_type="reasoning", input_prompt="do step 1"))
    wf.add_node(WorkflowNode(node_id="step2", task_type="reasoning", input_prompt="do step 2", depends_on=["step1"]))
    return wf


# ─── WorkflowNode Tests ──────────────────────────────────────────────────────

class TestWorkflowNode:
    def test_default_status_is_pending(self):
        node = WorkflowNode(node_id="n1", task_type="reasoning", input_prompt="hello")
        assert node.status == "pending"

    def test_no_dependencies_by_default(self):
        node = WorkflowNode(node_id="n1", task_type="reasoning", input_prompt="hello")
        assert node.depends_on == []

    def test_with_dependencies(self):
        node = WorkflowNode(node_id="n2", task_type="reasoning", input_prompt="world", depends_on=["n1"])
        assert "n1" in node.depends_on


# ─── Workflow Execution Tests ─────────────────────────────────────────────────

class TestWorkflow:
    def test_add_node(self, mock_engine):
        wf = Workflow(workflow_id="wf1", engine=mock_engine)
        wf.add_node(WorkflowNode(node_id="n1", task_type="reasoning", input_prompt="test"))
        assert "n1" in wf.nodes

    @pytest.mark.asyncio
    async def test_run_sequential_dag(self, simple_workflow, mock_engine):
        """Steps execute in topological order."""
        with patch.object(simple_workflow, '_publish_event'):
            await simple_workflow.run()
        
        assert simple_workflow.nodes["step1"].status == "completed"
        assert simple_workflow.nodes["step2"].status == "completed"
        assert mock_engine.process.call_count == 2

    @pytest.mark.asyncio
    async def test_dependency_respected(self, simple_workflow, mock_engine):
        """step2 should only run after step1 is done."""
        call_order = []
        def track_call(task):
            # task_id format: "{workflow_id}_{node_id}"
            node_id = task.task_id.split("_", 1)[-1].replace("test_wf_", "")
            call_order.append(task.task_id.split("_")[-1])  # last segment = node_id
            return {"status": "completed", "output": "done"}

        mock_engine.process.side_effect = track_call
        with patch.object(simple_workflow, '_publish_event'):
            await simple_workflow.run()

        assert call_order == ["step1", "step2"]

    @pytest.mark.asyncio
    async def test_failed_node_stops_workflow(self, mock_engine):
        """If a node fails, the workflow should stop."""
        mock_engine.process.return_value = {"status": "failed", "output": "error"}
        wf = Workflow(workflow_id="fail_wf", engine=mock_engine)
        wf.add_node(WorkflowNode(node_id="n1", task_type="reasoning", input_prompt="fail me"))
        wf.add_node(WorkflowNode(node_id="n2", task_type="reasoning", input_prompt="never run", depends_on=["n1"]))
        
        with patch.object(wf, '_publish_event'):
            await wf.run()

        assert wf.nodes["n1"].status == "failed"
        assert wf.nodes["n2"].status == "failed"  # cascaded failure

    @pytest.mark.asyncio
    async def test_red_light_stops_workflow(self, mock_engine):
        """RED gate decision should halt the workflow."""
        mock_engine.process.return_value = {"status": "pending_h", "level": "red"}
        wf = Workflow(workflow_id="red_wf", engine=mock_engine)
        wf.add_node(WorkflowNode(node_id="n1", task_type="reasoning", input_prompt="risky"))
        wf.add_node(WorkflowNode(node_id="n2", task_type="reasoning", input_prompt="never", depends_on=["n1"]))

        with patch.object(wf, '_publish_event'):
            with patch.object(wf, '_publish_human_approval_event'):
                await wf.run()

        assert wf.nodes["n1"].status == "awaiting_approval"  # human-in-the-loop, not failed

    @pytest.mark.asyncio
    async def test_upstream_output_injected_into_downstream(self, mock_engine):
        """Downstream nodes receive upstream output in their prompt."""
        mock_engine.process.return_value = {"status": "completed", "output": "upstream result"}
        wf = Workflow(workflow_id="ctx_wf", engine=mock_engine)
        wf.add_node(WorkflowNode(node_id="n1", task_type="reasoning", input_prompt="step 1"))
        wf.add_node(WorkflowNode(node_id="n2", task_type="reasoning", input_prompt="step 2", depends_on=["n1"]))

        with patch.object(wf, '_publish_event'):
            with patch.object(wf, '_publish_human_approval_event'):
                await wf.run()

        # The second call's input should contain upstream output
        second_call_task = mock_engine.process.call_args_list[1][0][0]
        assert "upstream result" in second_call_task.input


# ─── WorkflowParser Tests ────────────────────────────────────────────────────

class TestWorkflowParser:
    def test_parse_valid_dict(self, mock_engine):
        parser = WorkflowParser(mock_engine)
        data = {
            "workflow_id": "test",
            "nodes": [
                {"id": "n1", "type": "research", "prompt": "do stuff"},
                {"id": "n2", "type": "reasoning", "prompt": "think", "depends_on": ["n1"]},
            ]
        }
        wf = parser.parse_dict(data)
        assert wf.workflow_id == "test"
        assert "n1" in wf.nodes
        assert "n2" in wf.nodes
        assert wf.nodes["n2"].depends_on == ["n1"]

    def test_missing_workflow_id_raises(self, mock_engine):
        parser = WorkflowParser(mock_engine)
        with pytest.raises(ValueError, match="workflow_id"):
            parser.parse_dict({"nodes": []})

    def test_missing_node_id_raises(self, mock_engine):
        parser = WorkflowParser(mock_engine)
        with pytest.raises(ValueError, match="id"):
            parser.parse_dict({"workflow_id": "x", "nodes": [{"type": "reasoning", "prompt": "bad"}]})

    def test_unknown_dependency_raises(self, mock_engine):
        parser = WorkflowParser(mock_engine)
        with pytest.raises(ValueError, match="unknown node"):
            parser.parse_dict({
                "workflow_id": "x",
                "nodes": [{"id": "n1", "type": "reasoning", "prompt": "hi", "depends_on": ["ghost"]}]
            })

    def test_self_dependency_raises(self, mock_engine):
        parser = WorkflowParser(mock_engine)
        with pytest.raises(ValueError, match="self-dependency"):
            parser.parse_dict({
                "workflow_id": "x",
                "nodes": [{"id": "n1", "type": "reasoning", "prompt": "hi", "depends_on": ["n1"]}]
            })

    def test_parse_file(self, mock_engine, tmp_path):
        import yaml
        data = {
            "workflow_id": "file_test",
            "nodes": [{"id": "step1", "type": "reasoning", "prompt": "hello"}]
        }
        f = tmp_path / "wf.yaml"
        f.write_text(yaml.dump(data))

        parser = WorkflowParser(mock_engine)
        wf = parser.parse_file(str(f))
        assert wf.workflow_id == "file_test"

    def test_parse_nonexistent_file_raises(self, mock_engine):
        parser = WorkflowParser(mock_engine)
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/tmp/nonexistent_12345.yaml")


# ─── WorkflowPlanner Tests ───────────────────────────────────────────────────

class TestWorkflowPlanner:
    def test_heuristic_research_task(self, mock_engine):
        planner = WorkflowPlanner(mock_engine, use_llm=False)
        wf = planner.plan("研究 LLM 的最新进展")
        assert len(wf.nodes) >= 2
        # Should have a research node
        types = [n.task_type for n in wf.nodes.values()]
        assert "research" in types

    def test_heuristic_write_task(self, mock_engine):
        planner = WorkflowPlanner(mock_engine, use_llm=False)
        wf = planner.plan("写一篇关于 AI 的文章")
        assert len(wf.nodes) >= 2
        # outline → draft → review pattern
        assert "outline" in wf.nodes

    def test_heuristic_code_task(self, mock_engine):
        planner = WorkflowPlanner(mock_engine, use_llm=False)
        wf = planner.plan("实现一个 Redis 缓存层")
        assert "design" in wf.nodes
        assert "implement" in wf.nodes

    def test_heuristic_plan_task(self, mock_engine):
        planner = WorkflowPlanner(mock_engine, use_llm=False)
        wf = planner.plan("规划下个季度的技术路线图")
        assert "situation" in wf.nodes
        assert "plan" in wf.nodes

    def test_heuristic_default_fallback(self, mock_engine):
        """Unknown task type falls back to default template."""
        planner = WorkflowPlanner(mock_engine, use_llm=False)
        wf = planner.plan("做一件很奇怪的事情")
        assert len(wf.nodes) == 2
        assert "understand" in wf.nodes
        assert "execute" in wf.nodes

    def test_llm_failure_falls_back_to_heuristic(self, mock_engine):
        """If LLM call fails, heuristic is used instead."""
        planner = WorkflowPlanner(mock_engine, use_llm=True)
        with patch.object(planner, '_plan_with_llm', return_value=None):
            wf = planner.plan("研究某个话题")
        assert len(wf.nodes) >= 2

    def test_llm_returns_valid_dag(self, mock_engine):
        """If LLM returns valid JSON, it's used directly."""
        planner = WorkflowPlanner(mock_engine, use_llm=True)
        llm_dag = {
            "workflow_id": "llm_generated",
            "name": "LLM Plan",
            "nodes": [
                {"id": "step1", "type": "research", "prompt": "collect info"},
                {"id": "step2", "type": "reasoning", "prompt": "analyze", "depends_on": ["step1"]},
            ]
        }
        with patch.object(planner, '_plan_with_llm', return_value=llm_dag):
            wf = planner.plan("some task")
        assert wf.workflow_id == "llm_generated"
        assert len(wf.nodes) == 2

    def test_extract_json_strips_think_tags(self, mock_engine):
        planner = WorkflowPlanner(mock_engine)
        text = '<think>I need to think...</think>\n{"workflow_id": "x", "nodes": []}'
        result = planner._extract_json(text)
        assert result is not None
        assert result["workflow_id"] == "x"

    def test_extract_json_from_markdown_block(self, mock_engine):
        planner = WorkflowPlanner(mock_engine)
        text = '```json\n{"workflow_id": "y", "nodes": []}\n```'
        result = planner._extract_json(text)
        assert result["workflow_id"] == "y"
