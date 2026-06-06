import sys
import asyncio
from pathlib import Path
import logging

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from metaos.core.engine import SEngine
from metaos.core.workflow import Workflow, WorkflowNode

logging.basicConfig(level=logging.INFO)

async def run_test_workflow():
    print("🚀 Initializing SEngine...")
    engine = SEngine()
    
    # We need a token to use SEngine process()
    token = engine.register_h("metaos_system", "Automated Workflow")
    engine.authenticate(token)
    
    print("📦 Creating DAG Workflow: P35-T3-MVP")
    wf = Workflow(workflow_id="P35-T3-MVP", engine=engine)
    
    # Node 1: Research Phase
    wf.add_node(WorkflowNode(
        node_id="research_phase",
        task_type="info_retrieval",
        input_prompt="Research the concept of Multi-Agent Systems and summarize 3 key benefits."
    ))
    
    # Node 2: Synthesis Phase (depends on Research)
    wf.add_node(WorkflowNode(
        node_id="synthesis_phase",
        task_type="reasoning",
        input_prompt="Based on the following research, draft a short memo to the team.",
        depends_on=["research_phase"]
    ))
    
    # Node 3: Review Phase (depends on Synthesis)
    wf.add_node(WorkflowNode(
        node_id="review_phase",
        task_type="reasoning",
        input_prompt="Review this memo for clarity and conciseness. Suggest 1 improvement.",
        depends_on=["synthesis_phase"]
    ))
    
    print("⚙️ Executing Workflow...")
    await wf.run()
    
    print("\n🏁 Workflow Execution Results:")
    for node_id, node in wf.nodes.items():
        print(f"[{node.status}] {node_id}:")
        if node.output:
            print(f"  -> {node.output[:100]}...\n")

if __name__ == "__main__":
    asyncio.run(run_test_workflow())
