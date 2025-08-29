import base64
import os
import asyncio
import datetime
from langgraph.prebuilt import create_react_agent
from core.config import settings
from .models import Transactions, CategorizedTransaction, GraphState
from core.database import get_category_by_merchant, get_categories
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_tavily import TavilySearch
from langgraph.config import get_stream_writer
from browser_use import Agent as BrowserAgent
from browser_use import BrowserSession
from browser_use.llm import ChatAzureOpenAI
from browser_use import BrowserProfile

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


def browse_credit_card_node(state: GraphState) -> list[Transactions]:
    """
    Logs into the credit card issuer's website and extracts current-month transactions.
    Uses Browser Use to launch Chromium, navigates with Playwright Page (DOM ready), then Azure OpenAI to extract transactions.
    """
    writer = get_stream_writer()
    writer({"step": "web_browse", "message": "🌐 Launching headless browser to fetch transactions..."})

    login_url = settings.CREDIT_CARD_ISSUER_LOGIN_URL
    tx_url = settings.CREDIT_CARD_ISSUER_TRANSACTIONS_URL
    username = settings.CREDIT_CARD_ISSUER_USERNAME
    password = settings.CREDIT_CARD_ISSUER_PASSWORD

    # Browser Use (async) flow using Playwright Page from the session's browser_context
    page_text = ""
    async def _run_browser_use() -> str:
        profile = BrowserProfile(
            headless=True,
            keep_alive=True,
            enable_default_extensions=False,
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        )
        session = BrowserSession(
            browser_profile=profile,
        )

        writer({"step": "web_browse", "message": "🚀 Starting BrowserSession..."})
        await session.start()
        writer({"step": "web_browse", "message": "✅ BrowserSession started"})
 
        # Create a single BrowserAgent and instruct it to navigate via tasks (persistent session)
        bu_llm = ChatAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            azure_deployment="gpt-4.1",
            api_version=settings.OPENAI_API_VERSION,
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        )
        # Compute current date and month context
        _today = datetime.date.today()
        _month_prefix = _today.strftime("%Y-%m")
        _today_str = _today.strftime("%Y-%m-%d")

        combined_task = (
            f"go_to_url {login_url}. Log in using the provided username and password. "
            "Wait until you clearly see a logged-in indicator (e.g., avatar/user menu). "
            f"Then go_to_url {tx_url} and ensure the transactions view is fully visible. "
            f"Context: today is {_today_str}. Current month is '{_month_prefix}'. "
            "Task: collect all transactions that belong to the current month only. Use your own reasoning to apply any date filters, navigate, scroll, and paginate as needed to ensure coverage. "
            "Return the transactions as a JSON array in extracted content with keys: merchant (string), amount (number), date (YYYY-MM-DD). "
            "IMPORTANT: Make sure you have collected all transactions for the current month and nothinng is missed. "
            "Do not download files and do not close the tab. "
            "When extraction is complete, reply with EXACTLY: READY_TX."
        )
        agent = BrowserAgent(
            task=combined_task,
            llm=bu_llm,
            browser_session=session,
            sensitive_data={"username": username, "password": password},
            output_model_schema=Transactions
        )
        try:
            writer({"step": "web_browse", "message": "🤖 Agent start running..."})
            history = await agent.run(max_steps=10)
            writer({"step": "web_browse", "message": "🤖 Agent finish running"})
            content_items = history.extracted_content() or []
            final_result = history.final_result()
            parsed_transactions = Transactions.model_validate_json(final_result)
            writer({"step": "web_browse", "message": f"🤖 Agent return parsed {len(parsed_transactions.transactions)} transactions"})
            return parsed_transactions.transactions
        finally:
            # Always terminate the browser to free resources
            try:
                await session.kill()
                writer({"step": "web_browse", "message": "🛑 BrowserSession closed"})
            except Exception:
                pass


    try:
        web_transactions = asyncio.run(_run_browser_use())
        return {"transactions": web_transactions}
    except Exception as e:
        writer({"step": "web_browse", "message": f"❌ Error during web browsing: {str(e)}"})
        return {"transactions": []}

    # # Use Azure LLM to extract transactions from text
    # llm = AzureChatOpenAI(
    #     api_key=settings.AZURE_OPENAI_API_KEY,
    #     azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    #     azure_deployment="gpt-4.1",
    #     model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
    #     api_version=settings.OPENAI_API_VERSION
    # )
    # structured_llm = llm.with_structured_output(Transactions)
    # try:
    #     writer({"step": "web_browse", "message": "🧠 Extracting transactions from page text..."})
    #     prompt = (
    #         "Extract all transactions visible in the following page text. "
    #         "Return only merchant (string), amount (number), date (YYYY-MM-DD).\n\n"
    #         f"PAGE TEXT:\n{page_text}"
    #     )
    #     resp = structured_llm.invoke([HumanMessage(content=prompt)])
    #     count = len(resp.transactions)
    #     writer({"step": "web_browse", "message": f"✅ Extracted {count} transaction(s) from web page"})
    #     return {"transactions": resp.transactions}
    # except Exception as e:
    #     writer({"step": "web_browse", "message": f"❌ Error extracting transactions: {str(e)}"})
    #     return {"transactions": []} 