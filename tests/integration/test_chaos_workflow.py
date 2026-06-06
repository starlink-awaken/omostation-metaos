import asyncio
import logging
from unittest.mock import MagicMock
import pytest
from metaos.core.workflow import Workflow, WorkflowNode
from metaos.core.engine import SEngine

logging.basicConfig(level=logging.INFO)

@pytest.mark.asyncio
async def test_chaos_timeout_and_cascade():
    """
    Chaos Engineering: Simulate a node taking too long and triggering a timeout,
    ensuring it cascade-fails all downstream nodes but doesn't block the parallel ones.
    """
    mock_engine = MagicMock(spec=SEngine)
    
    # We will simulate that 'gather_academic' hangs forever (Chaos)
    # while 'gather_web' finishes normally.
    def chaotic_process(task):
        import time
        node_id = task.task_id.split("_")[-1]
        if "academic" in node_id:
            print(f"😈 [Chaos] Injecting delay into {node_id}!")
            time.sleep(3)  # Simulate hang
            return {"status": "completed"}
        else:
            print(f"✅ [Normal] Processing {node_id} normally.")
            time.sleep(0.1)
            return {"status": "completed", "output": "Normal Result"}

    mock_engine.process.side_effect = chaotic_process
    
    wf = Workflow("chaos_wf", mock_engine)
    wf.add_node(WorkflowNode(node_id="gather_web", task_type="mock_task", input_prompt="Web"))
    # Set a very short timeout to trigger the chaos cascade fast!
    wf.add_node(WorkflowNode(node_id="gather_academic", task_type="mock_task", input_prompt="Academic", timeout_seconds=1))
    wf.add_node(WorkflowNode(node_id="synthesize", task_type="reasoning", input_prompt="Combine", depends_on=["gather_web", "gather_academic"]))
    
    print("\n🚀 Starting Chaotic Workflow Execution...")
    await wf.run()
    
    print("\n🏁 Asserting Chaos Results:")
    assert wf.nodes["gather_web"].status == "completed", "Independent node should complete"
    assert wf.nodes["gather_academic"].status == "timed_out", "Hanging node should fail via timeout"
    assert wf.nodes["synthesize"].status == "failed", "Downstream node should cascade-fail"
    print("✨ Chaos Test Passed! System is Anti-Fragile.")

if __name__ == "__main__":
    asyncio.run(test_chaos_timeout_and_cascade())
