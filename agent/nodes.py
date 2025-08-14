import base64
from langgraph.prebuilt import create_react_agent
from core.config import settings
from .models import Transactions, CategorizedTransaction, GraphState
from core.database import get_category_by_merchant, get_categories
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_tavily import TavilySearch
from langgraph.config import get_stream_writer

# --- Graph Nodes ---

def extract_transaction_node(state: GraphState):
    """
    Extracts merchant and amount from a receipt image.
    """
    writer = get_stream_writer()
    writer({"step": "image_extraction", "message": "🖼️ Analyzing receipt image..."})
    
    image_bytes = state["image_bytes"]

    llm = AzureChatOpenAI(
        azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        openai_api_version=settings.OPENAI_API_VERSION
    )
    structured_llm = llm.with_structured_output(Transactions)
    
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    message = HumanMessage(
        content=[
            {"type": "text", "text": "You are an expert receipt scanner. Extract all transactions from this receipt image, including their merchant, total amount, and date (in YYYY-MM-DD format) example date 13/07/25 means 13th of July 2025."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
    )
    try:
        writer({"step": "image_extraction", "message": "🔍 Processing image with AI..."})
        response = structured_llm.invoke([message])
        
        count = len(response.transactions)
        writer({"step": "image_extraction", "message": f"✅ Extracted {count} transaction(s) from image"})
        
        return {"transactions": response.transactions}
    except Exception as e:
        writer({"step": "image_extraction", "message": f"❌ Error extracting from image: {str(e)}"})
        return {"transactions": []}


def extract_text_transaction_node(state: GraphState):
    """
    Extracts transactions from text data (e.g., Excel file content).
    """
    writer = get_stream_writer()
    writer({"step": "text_extraction", "message": "📄 Analyzing Excel file content..."})
    
    text_data = state["text_data"]

    llm = AzureChatOpenAI(
        azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        openai_api_version=settings.OPENAI_API_VERSION
    )
    structured_llm = llm.with_structured_output(Transactions)
    
    message = HumanMessage(
        content=f"""You are an expert financial data analyzer. Extract all transactions from the following data.
        Look for patterns that indicate merchant names, amounts, and dates.
        
        For dates, convert any format to YYYY-MM-DD. Common formats include:
        - DD/MM/YY or DD/MM/YYYY
        - MM/DD/YY or MM/DD/YYYY  
        - DD-MM-YY or DD-MM-YYYY
        - Text dates like "Jan 15, 2024"
        
        For amounts, look for currency symbols or numerical values that represent money.
        
        Here is the data to analyze:
        
        {text_data}
        """
    )
    
    try:
        writer({"step": "text_extraction", "message": "🤖 Processing text data with AI..."})
        response = structured_llm.invoke([message])
        
        count = len(response.transactions)
        writer({"step": "text_extraction", "message": f"✅ Extracted {count} transaction(s) from text"})
        
        return {"transactions": response.transactions}
    except Exception as e:
        writer({"step": "text_extraction", "message": f"❌ Error extracting from text: {str(e)}"})
        return {"transactions": []}


def classify_transaction_node(state: GraphState) -> GraphState:
    """Classifies a single transaction by looking up the merchant or using an LLM."""
    writer = get_stream_writer()
    writer({"step": "classification", "message": "🏷️ Starting transaction classification..."})
    
    categorized_transactions = []
    all_categories = [cat['name'] for cat in get_categories()] # Fetch all category names once
    transactions = state["transactions"]
    
    writer({"step": "classification", "message": f"🔄 Processing {len(transactions)} transaction(s)..."})

    for i, tx in enumerate(transactions):
        writer({"step": "classification", "message": f"🔍 Classifying transaction {i+1}/{len(transactions)}: {tx.merchant}"})
        
        # 1. Check if the merchant is already known
        category = get_category_by_merchant(tx.merchant)

        # 2. If not known, use the LLM to classify
        if not category:
            writer({"step": "classification", "message": f"🤖 Using AI to classify '{tx.merchant}'"})
            llm = AzureChatOpenAI(
                azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                openai_api_version=settings.OPENAI_API_VERSION
            )
            tools = [TavilySearch(max_results=1)]
            agent_executor = create_react_agent(llm, tools)
            
            prompt = (
                f"You are an expert financial assistant. Your goal is to categorize the transaction with merchant "
                f"'{tx.merchant}' into one of the following categories: {', '.join(all_categories)}. "
                f"Use the search tool to find out more about the merchant if you are unsure. "
                f"Your final answer should be ONLY the category name."
            )
            try:
                response = agent_executor.invoke({"messages": [("user", prompt)]})
                predicted_category = response['messages'][-1].content.strip()
                # Ensure the predicted category is one of the valid categories
                if predicted_category in all_categories:
                    category = predicted_category
                    writer({"step": "classification", "message": f"✅ AI classified '{tx.merchant}' as '{category}'"})
                else:
                    category = "Uncategorized" # Fallback if LLM hallucinates a new category
                    writer({"step": "classification", "message": f"⚠️ AI gave invalid category, using 'Uncategorized' for '{tx.merchant}'"})
            except Exception as e:
                writer({"step": "classification", "message": f"❌ Error classifying '{tx.merchant}': {str(e)}"})
                category = "Uncategorized"
        else:
            writer({"step": "classification", "message": f"💾 Found existing category '{category}' for '{tx.merchant}'"})

        categorized_transactions.append(
            CategorizedTransaction(
                merchant=tx.merchant,
                amount=tx.amount,
                date=tx.date,
                category=category,
            )
        )
    
    writer({"step": "classification", "message": f"🎉 Classification complete! Processed {len(categorized_transactions)} transaction(s)"})
    return {"categorized_transactions": categorized_transactions} 