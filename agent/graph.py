from typing import List, Literal
from langgraph.graph import StateGraph, END, START
from agent.models import GraphState
from agent.nodes import extract_transaction_node, extract_text_transaction_node, classify_transaction_node

# --- Graph Definition ---

def route_extraction(state: GraphState) -> Literal["image_extractor", "text_extractor"]:
    """
    Route to the appropriate extraction node based on input type.
    
    Args:
        state (GraphState): The current graph state
        
    Returns:
        str: Next node to call ("image_extractor" or "text_extractor")
    """
    input_type = state.get("input_type", "image")  # Default to image if not specified
    
    if input_type == "text":
        print("---ROUTING TO TEXT EXTRACTOR---")
        return "text_extractor"
    else:
        print("---ROUTING TO IMAGE EXTRACTOR---")
        return "image_extractor"


def build_agent():
    workflow = StateGraph(GraphState)

    # Add the nodes
    workflow.add_node("image_extractor", extract_transaction_node)
    workflow.add_node("text_extractor", extract_text_transaction_node)
    workflow.add_node("classifier", classify_transaction_node)

    # Add conditional routing from START based on input type
    workflow.add_conditional_edges(
        START,
        route_extraction,
        {
            "image_extractor": "image_extractor",
            "text_extractor": "text_extractor"
        }
    )

    # Both extractors go to the classifier
    workflow.add_edge("image_extractor", "classifier")
    workflow.add_edge("text_extractor", "classifier")
    workflow.add_edge("classifier", END)

    # Compile the graph
    return workflow.compile()


# --- Agent Runner ---

def run_agent(image_bytes: bytes = None, text_data: str = None, categories: List[str] = None):
    """
    Runs the full transaction processing agent.
    
    Args:
        image_bytes (bytes, optional): Raw bytes of an image (for receipt processing)
        text_data (str, optional): Text content to process (for Excel/CSV processing)
        categories (List[str], optional): List of available categories
    
    Returns:
        List of categorized transactions
    """
    if categories is None:
        categories = []
    
    # Determine input type and prepare inputs
    if text_data is not None:
        inputs = {
            "image_bytes": b"",  # Required by TypedDict but not used
            "text_data": text_data,
            "input_type": "text",
            "categories": categories,
        }
    elif image_bytes is not None:
        inputs = {
            "image_bytes": image_bytes,
            "text_data": "",  # Required by TypedDict but not used
            "input_type": "image",
            "categories": categories,
        }
    else:
        raise ValueError("Either image_bytes or text_data must be provided")
    
    app = build_agent()
    final_state = app.invoke(inputs)
    return final_state.get("categorized_transactions") 