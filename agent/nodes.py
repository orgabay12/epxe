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
import re
import unicodedata
from agent.sanitize import sanitize_merchant

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


def browse_credit_card_node(state: GraphState):
    """
    Logs into the credit card issuer's website and extracts current-month transactions.
    Uses browser-use with Azure OpenAI.
    """
    writer = get_stream_writer()
    writer({"step": "web_browse", "message": "🌐 Launching headless browser to fetch transactions..."})

    login_url = settings.CREDIT_CARD_ISSUER_LOGIN_URL
    tx_url = settings.CREDIT_CARD_ISSUER_TRANSACTIONS_URL
    username = settings.CREDIT_CARD_ISSUER_USERNAME
    password = settings.CREDIT_CARD_ISSUER_PASSWORD

    bu_llm = ChatAzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        azure_deployment="gpt-4.1",
        model="gpt-4.1",
        api_version=settings.OPENAI_API_VERSION
    )

    async def _browser_agent_run() -> str:
        # Force using Playwright Chromium (avoid branded Chrome install attempts)
        os.environ.setdefault("BROWSER_USE_BROWSER", "playwright:chromium")
        os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "debug")
        from browser_use import BrowserProfile
        profile = BrowserProfile(
            headless=True,
            user_data_dir=None,
            enable_default_extensions=False,
            highlight_elements=False,
            default_timeout=60000,
            default_navigation_timeout=60000,
            wait_for_network_idle_page_load_time=1.5,
        )
        session = BrowserSession(
            browser_profile=profile,
            keep_alive=True,
        )
        today = datetime.date.today()
        current_date = today.strftime("%Y-%m-%d")
        current_month = today.strftime("%Y-%m")
        # Start the session and open the login page up-front
        writer({"step": "web_browse", "message": "🚀 Starting BrowserSession..."})
        await session.start()
        writer({"step": "web_browse", "message": "✅ BrowserSession started"})
        writer({"step": "web_browse", "message": "🧭 Getting current page handle..."})
        page = session.agent_current_page
        if (page is None) or page.is_closed():
            writer({"step": "web_browse", "message": "ℹ️ No active page; opening new tab..."})
            assert session.browser_context is not None, "Browser context not available"
            page = await session.browser_context.new_page()
            writer({"step": "web_browse", "message": "🆕 Opened fresh tab"})
        else:
            writer({"step": "web_browse", "message": "🧭 Got page handle"})
        writer({"step": "web_browse", "message": f"➡️ Navigating: {login_url}"})
        await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        writer({"step": "web_browse", "message": "✅ Login page loaded"})
        # Stage 1: Login
        writer({"step": "web_browse", "message": "🤖 Running login agent..."})
        login_agent = BrowserAgent(
            task=(
                f"1. You are on {login_url}.\n"
                f"2. Log in with username '{username}' and password '{password}'.\n"
                f"3. Finish as soon as the account area/dashboard is visible. Do not extract data in this stage."
            ),
            llm=bu_llm,
            page=page,
            browser_session=session
        )
        await login_agent.run(max_steps=25)
        writer({"step": "web_browse", "message": "✅ Login agent finished"})
 
        # Manual navigation to transactions page
        # Reacquire page in case the agent switched tabs or the handle changed
        writer({"step": "web_browse", "message": "🧭 Getting current page for transactions..."})
        page = session.agent_current_page
        if (page is None) or page.is_closed():
            writer({"step": "web_browse", "message": "ℹ️ No active page; opening new tab..."})
            assert session.browser_context is not None, "Browser context not available"
            page = await session.browser_context.new_page()
            writer({"step": "web_browse", "message": "🆕 Opened fresh tab"})
        writer({"step": "web_browse", "message": f"➡️ Navigating: {tx_url}"})
        await page.goto(tx_url, wait_until="domcontentloaded", timeout=60000)
        writer({"step": "web_browse", "message": "✅ Transactions page loaded"})
 
        # Stage 2: Extraction (text-only)
        writer({"step": "web_browse", "message": "🧠 Running extraction agent..."})
        agent = BrowserAgent(
            task=(
                f"You are on the transactions page {tx_url}. Today's date is {current_date}.\n"
                f"1. Ensure the date filter is set to the current month ({current_month}).\n"
                f"2. Extract transactions using ONLY textual DOM content (innerText). Do NOT rely on images or OCR.\n"
                f"3. Extract a table of transactions with columns merchant, amount, date.\n"
                f"4. IMPORTANT: Do not include escaped unicode sequences (e.g., \\u0022) or HTML entities (e.g., &quot;). Use plain characters only.\n"
                f"5. Return ONLY a JSON array with objects: {{merchant: string, amount: number, date: 'YYYY-MM-DD'}}."
            ),
            llm=bu_llm,
            page=page,
            browser_session=session,
            use_vision=False,
            use_vision_for_planner=True
        )

        try:
            history = await agent.run(max_steps=40)
            writer({"step": "web_browse", "message": "✅ Extraction agent finished"})
            # Try common helpers to get final text content
            raw = None
            try:
                final_result = getattr(history, "final_result", None)
                raw = final_result() if callable(final_result) else None
            except Exception:
                raw = None
            if not raw:
                try:
                    extracted = getattr(history, "extracted_content", None)
                    raw = extracted() if callable(extracted) else None
                except Exception:
                    raw = None
            return raw if isinstance(raw, str) else str(history)
        finally:
            try:
                if hasattr(session, "close"):
                    await session.close()
            except Exception:
                pass
            # Ensure the browser fully terminates
            try:
                if hasattr(session, "kill"):
                    await session.kill()
            except Exception:
                pass

    try:
        raw_content = asyncio.run(_browser_agent_run())
        llm = AzureChatOpenAI(
            azure_deployment='gpt-4.1',
            openai_api_version=settings.OPENAI_API_VERSION
        )
        structured_llm = llm.with_structured_output(Transactions)
        message = HumanMessage(content=(
            "You are a strict validator. Convert the following to the schema Transactions[merchant, amount, date(YYYY-MM-DD)].\n"
            "Do NOT emit escaped unicode sequences (e.g., \\uXXXX) or HTML entities (e.g., &quot;). Output plain characters only.\n"
            f"Input:\n{raw_content}"
        ))
        validated = structured_llm.invoke([message])
        count = len(validated.transactions)
        writer({"step": "web_browse", "message": f"✅ Extracted {count} transaction(s) from issuer website"})
        return {"transactions": validated.transactions}

    except Exception as e:
        print(e)
        writer({"step": "web_browse", "message": f"❌ Error during web browsing: {str(e)}"})
        return {"transactions": []} 