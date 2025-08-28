from typing import List, Literal
from langgraph.graph import StateGraph, END, START
from agent.models import GraphState
from agent.nodes import extract_transaction_node, extract_text_transaction_node, classify_transaction_node
from agent.nodes import browse_credit_card_node
# --- Graph Definition ---

def route_extraction(state: GraphState) -> Literal["image_extractor", "text_extractor", "web_extractor"]:
    """
    Route to the appropriate extraction node based on input type.
    
    Args:
        state (GraphState): The current graph state
        
    Returns:
        str: Next node to call ("image_extractor", "text_extractor", or "web_extractor")
    """
    input_type = state.get("input_type", "image")  # Default to image if not specified
    
    if input_type == "text":
        print("---ROUTING TO TEXT EXTRACTOR---")
        return "text_extractor"
    elif input_type == "web":
        print("---ROUTING TO WEB EXTRACTOR---")
        return "web_extractor"
    else:
        print("---ROUTING TO IMAGE EXTRACTOR---")
        return "image_extractor"


def build_agent():
    workflow = StateGraph(GraphState)

    # Add the nodes
    workflow.add_node("image_extractor", extract_transaction_node)
    workflow.add_node("text_extractor", extract_text_transaction_node)
    workflow.add_node("classifier", classify_transaction_node)
    workflow.add_node("web_extractor", browse_credit_card_node)

    # Add conditional routing from START based on input type
    workflow.add_conditional_edges(
        START,
        route_extraction,
        {
            "image_extractor": "image_extractor",
            "text_extractor": "text_extractor",
            "web_extractor": "web_extractor",
        }
    )

    # All extractors go to the classifier
    workflow.add_edge("image_extractor", "classifier")
    workflow.add_edge("text_extractor", "classifier")
    workflow.add_edge("web_extractor", "classifier")
    workflow.add_edge("classifier", END)

    # Compile the graph
    return workflow.compile()