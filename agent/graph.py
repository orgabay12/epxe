from typing import List
from langgraph.graph import StateGraph, END
from agent.models import GraphState
from agent.nodes import extract_transaction_node, classify_transaction_node

# --- Graph Definition ---

def build_agent():
    workflow = StateGraph(GraphState)

    # Add the nodes
    workflow.add_node("extractor", extract_transaction_node)
    workflow.add_node("classifier", classify_transaction_node)

    # Set the entrypoint
    workflow.set_entry_point("extractor")

    # Add the edges
    workflow.add_edge("extractor", "classifier")
    workflow.add_edge("classifier", END)

    # Compile the graph
    return workflow.compile()


# --- Agent Runner ---

def run_agent(image_bytes: bytes, categories: List[str]):
    """
    Runs the full transaction processing agent.
    """
    app = build_agent()
    inputs = {
        "image_bytes": image_bytes,
        "categories": categories,
    }
    final_state = app.invoke(inputs)
    return final_state.get("categorized_transactions") 