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


def browse_credit_card_node(state: GraphState):
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
        # Force Browser Use to use Playwright Chromium, not patchright
        os.environ["BROWSER_USE_BROWSER"] = "playwright:chromium"
        os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "info")

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
            extra_launch_args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        writer({"step": "web_browse", "message": "🚀 Starting BrowserSession..."})
        await session.start()
        writer({"step": "web_browse", "message": "✅ BrowserSession started"})
 
        # Create a single BrowserAgent and instruct it to navigate via tasks (persistent session)
        bu_llm = ChatAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            api_version=settings.OPENAI_API_VERSION,
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        )
        task_login = (
            f"Open {login_url}. Use the supplied credentials (username and password) to log in. "
            "Wait for a clear post-login indicator (e.g., user menu, dashboard). "
            "Do not close the tab. When logged in, reply with EXACTLY: READY_LOGIN"
        )
        agent = BrowserAgent(
            task=task_login,
            llm=bu_llm,
            browser_session=session,
            sensitive_data={"username": username, "password": password},
        )
        try:
            writer({"step": "web_browse", "message": "🤖 Agent running: login task..."})
            page = agent.browser_session.agent_current_page
            writer({"step": "web_browse", "message": "🤖 Agent running: got current page"})
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            writer({"step": "web_browse", "message": "🤖 Agent running: navigated to login page"})
            history_login = await agent.run(max_steps=5)
            # Chain follow-up task to navigate to transactions
            task_tx = (
                f"Navigate to {tx_url}. Ensure the transactions table is visible on the page. "
                "Do not download files and do not close the tab. Reply with EXACTLY: READY_TX"
            )
            agent.add_new_task(task_tx)
            writer({"step": "web_browse", "message": "🤖 Agent running: transactions task..."})
            history_tx = await agent.run(max_steps=30)
            writer({"step": "web_browse", "message": "✅ Agent finished tasks, extracting content..."})

            # Prefer agent history extracted content per docs; fallback to reading the page body
            try:
                content_items = history_tx.extracted_content() or []
            except Exception:
                content_items = []
            text_from_history = "\n\n".join([c for c in content_items if isinstance(c, str)]).strip()
            if not text_from_history:
                try:
                    text_from_history = (history_tx.final_result() or "").strip()
                except Exception:
                    text_from_history = ""
            if text_from_history:
                return text_from_history

            page = session.agent_current_page or (session.browser_context.pages[0] if len(session.browser_context.pages) > 0 else await session.browser_context.new_page())
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=60000)
            except Exception:
                pass
            try:
                body = page.locator("body")
                text = await body.inner_text(timeout=5000)
            except Exception:
                text = await page.content()
            return text
        finally:
            # Always terminate the browser to free resources
            try:
                await session.close()
                writer({"step": "web_browse", "message": "🛑 BrowserSession closed"})
            except Exception:
                pass


    try:
        page_text = asyncio.run(_run_browser_use())
    except Exception as e:
        writer({"step": "web_browse", "message": f"❌ Error during web browsing: {str(e)}"})
        return {"transactions": []}

    # Use Azure LLM to extract transactions from text
    llm = AzureChatOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        api_version=settings.OPENAI_API_VERSION
    )
    structured_llm = llm.with_structured_output(Transactions)
    try:
        writer({"step": "web_browse", "message": "🧠 Extracting transactions from page text..."})
        prompt = (
            "Extract all transactions visible in the following page text. "
            "Return only merchant (string), amount (number), date (YYYY-MM-DD).\n\n"
            f"PAGE TEXT:\n{page_text}"
        )
        resp = structured_llm.invoke([HumanMessage(content=prompt)])
        count = len(resp.transactions)
        writer({"step": "web_browse", "message": f"✅ Extracted {count} transaction(s) from web page"})
        return {"transactions": resp.transactions}
    except Exception as e:
        writer({"step": "web_browse", "message": f"❌ Error extracting transactions: {str(e)}"})
        return {"transactions": []} 