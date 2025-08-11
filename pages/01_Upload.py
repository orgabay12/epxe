import streamlit as st
import datetime
import os
import core.database as db
from agent import run_agent
from core.auth import is_authenticated
import pandas as pd
from agent.graph import build_agent
import time

# --- Authentication Check ---
if not is_authenticated():
    st.warning("Please log in to access this page.")
    st.stop()

# --- Sidebar ---
st.sidebar.title("Navigation")
if st.sidebar.button("Logout"):
    st.session_state['action'] = 'logout'
    st.switch_page("Home.py")

st.title("💸 Upload Transactions")

# --- State Management (for non-persistent UI state) ---
if 'processed_file_id' not in st.session_state:
    st.session_state.processed_file_id = None

# Fetch categories from the database for use in the app
categories_list = db.get_categories()
categories_dict = {cat['name']: {'id': cat['id'], 'budget': float(cat['budget'])} for cat in categories_list}

# --- Tabs for different input methods ---
tab1, tab2, tab3 = st.tabs(["📄 AI Excel Processing", "🤖 AI Image Extraction", "📝 Manual Entry"])

with tab1:
    st.header("Upload an Excel File")
    st.write("Upload any Excel file with transaction data. Our AI will automatically extract merchant, amount, date, and category information.")
    
    uploaded_file = st.file_uploader(
        "Choose an Excel file",
        type=['xlsx', 'xls'],
        key="excel_uploader"
    )
    
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)

            if st.button("Process with AI"):
                # Create status container for streaming
                logs = []
                
                with st.status("📄 Processing Excel file...", expanded=True) as status:
                    try:
                        logs.append(f"📄 Reading Excel file... Found {len(df)} rows")
                        
                        # Convert entire DataFrame to text for the AI agent
                        file_content = df.to_string(index=False)
                        logs.append("🔄 Converting file content for AI analysis...")
                        
                        # Build the agent graph
                        app = build_agent()
                        
                        # Prepare inputs for text processing
                        inputs = {
                            "image_bytes": b"",
                            "text_data": file_content,
                            "input_type": "text",
                            "categories": list(categories_dict.keys()),
                        }
                        
                        log_placeholder = st.empty()
                        log_placeholder.text("\n".join(logs[-8:]))
                        
                        # Stream the graph execution
                        categorized_transactions = None
                        for chunk in app.stream(inputs, stream_mode="custom"):
                            if chunk:
                                step = chunk.get("step", "processing")
                                message = chunk.get("message", str(chunk))
                                logs.append(message)
                                
                                # Update the status and display latest logs
                                status.update(label=f"📄 Processing: {message[:50]}...", expanded=True)
                                log_placeholder.text("\n".join(logs[-8:]))
                        
                        # Get the final result
                        final_state = app.invoke(inputs)
                        categorized_transactions = final_state.get("categorized_transactions", [])
                        
                        if not categorized_transactions:
                            logs.append("⚠️ No transactions extracted")
                            status.update(label="⚠️ No transactions found", state="error", expanded=True)
                            log_placeholder.text("\n".join(logs[-8:]))
                            st.warning("No transactions were extracted from the file. Please check the file format.")
                        else:
                            logs.append(f"🔄 Processing and saving {len(categorized_transactions)} transaction(s)...")
                            status.update(label=f"💾 Saving {len(categorized_transactions)} transactions...", expanded=True)
                            log_placeholder.text("\n".join(logs[-8:]))
                            
                            added_count = 0
                            skipped_count = 0
                            errors = []
                            
                            for i, transaction in enumerate(categorized_transactions):
                                try:
                                    merchant = transaction.merchant
                                    amount = transaction.amount
                                    date = transaction.date
                                    category = transaction.category
                                    
                                    # Basic validation
                                    if not merchant or not amount or not date:
                                        error_msg = f"Transaction {i+1}: Missing required information - {merchant}, {amount}, {date}"
                                        errors.append(error_msg)
                                        logs.append(f"⚠️ {error_msg}")
                                        skipped_count += 1
                                        continue
                                    
                                    # Check for duplicates via identifier (merchant+date)
                                    if not db.transaction_exists_by_identifier(merchant, date):
                                        db.add_expense(merchant, float(amount), date, category)
                                        logs.append(f"✅ Added: {merchant} - ₪{amount} ({category})")
                                        added_count += 1
                                    else:
                                        logs.append(f"⏭️ Skipped duplicate (same day): {merchant} - ₪{amount}")
                                        skipped_count += 1
                                    
                                    # Update the display periodically
                                    if (i + 1) % 5 == 0 or i == len(categorized_transactions) - 1:
                                        log_placeholder.text("\n".join(logs[-8:]))
                                        
                                except Exception as e:
                                    error_msg = f"Transaction {i+1}: Error processing - {str(e)}"
                                    errors.append(error_msg)
                                    logs.append(f"❌ {error_msg}")
                                    skipped_count += 1
                            
                            logs.append(f"🎉 Processing complete! Added {added_count}, skipped {skipped_count}")
                            status.update(label=f"✅ Complete! Added {added_count}, skipped {skipped_count}", state="complete", expanded=True)
                            log_placeholder.text("\n".join(logs[-8:]))
                            
                            # Show results
                            st.success(f"Processing complete! Added {added_count} new transactions. Skipped {skipped_count} transactions.")
                            
                            if errors:
                                with st.expander(f"View {len(errors)} Processing Errors"):
                                    for error in errors[:10]:  # Show first 10 errors
                                        st.warning(error)
                                    if len(errors) > 10:
                                        st.info(f"... and {len(errors) - 10} more errors.")
                    
                    except Exception as e:
                        logs.append(f"❌ Error: {str(e)}")
                        status.update(label=f"❌ Error occurred", state="error", expanded=True)
                        log_placeholder.text("\n".join(logs[-8:]))
                        st.error(f"Error processing file with AI: {str(e)}")

        except Exception as e:
            st.error(f"An error occurred while reading the file: {e}")

with tab2:
    st.header("Add Transaction via Receipt")

    uploaded_file = st.file_uploader("Upload a receipt image", type=["jpg", "jpeg", "png"])

    # Reset the processed file ID if the uploader is cleared by the user
    if uploaded_file is None:
        st.session_state.processed_file_id = None

    # Process the file only if it's a new, unprocessed file
    if uploaded_file is not None and uploaded_file.file_id != st.session_state.get('processed_file_id'):
        image_bytes = uploaded_file.getvalue()
        
        # Create status container for streaming
        logs = []
        
        with st.status("🤖 Processing receipt...", expanded=True) as status:
            # Build the agent graph
            app = build_agent()
            
            # Prepare inputs for image processing
            inputs = {
                "image_bytes": image_bytes,
                "text_data": "",
                "input_type": "image",
                "categories": list(categories_dict.keys()),
            }
            
            log_placeholder = st.empty()
            
            # Stream the graph execution
            categorized_transactions = None
            for chunk in app.stream(inputs, stream_mode="custom"):
                if chunk:
                    step = chunk.get("step", "processing")
                    message = chunk.get("message", str(chunk))
                    logs.append(message)
                    
                    # Update the status and display latest logs
                    status.update(label=f"🤖 Processing: {message[:50]}...", expanded=True)
                    log_placeholder.text("\n".join(logs[-8:]))  # Show last 8 logs
            
            # Get the final result
            final_state = app.invoke(inputs)
            categorized_transactions = final_state.get("categorized_transactions", [])
            
            # Process and save transactions
            added_count = 0
            skipped_count = 0
            if categorized_transactions:
                for tx in categorized_transactions:
                    # Check for duplicates before adding
                    if not db.transaction_exists_by_identifier(tx.merchant, tx.date):
                        db.add_expense(tx.merchant, tx.amount, tx.date, tx.category)
                        logs.append(f"✅ Added: {tx.merchant} - ₪{tx.amount}")
                        added_count += 1
                    else:
                        logs.append(f"⏭️ Skipped duplicate (same day): {tx.merchant} - ₪{tx.amount}")
                        skipped_count += 1
                        
                    # Update the display
                    log_placeholder.text("\n".join(logs[-8:]))

            logs.append(f"🎉 Completed! Added {added_count} transactions, skipped {skipped_count}")
            status.update(label=f"✅ Complete! Added {added_count}, skipped {skipped_count}", state="complete", expanded=True)
            log_placeholder.text("\n".join(logs[-8:]))
            
            if added_count > 0:
                st.success(f"Successfully added {added_count} new transaction(s).")

        # Mark this file as processed
        st.session_state.processed_file_id = uploaded_file.file_id

with tab3:
    st.header("Add a New Transaction")

    with st.form("transaction_form", clear_on_submit=True):
        merchant = st.text_input("Merchant")
        amount = st.number_input("Amount (₪)", min_value=0.0, format="%.2f")
        date = st.date_input("Date", value=datetime.date.today())

        category_options = list(categories_dict.keys())
        category = st.selectbox("Category", options=category_options, index=category_options.index('Uncategorized') if 'Uncategorized' in category_options else 0)

        add_transaction_submitted = st.form_submit_button("Add Transaction")
        if add_transaction_submitted:
            if merchant and amount > 0:
                # Check for duplicates before adding
                if not db.transaction_exists_by_identifier(merchant, date.strftime("%Y-%m-%d")):
                    db.add_expense(merchant, amount, date.strftime("%Y-%m-%d"), category)
                    st.success("Transaction added!")
                else:
                    st.warning("This transaction already exists (same merchant for the selected date).")
            else:
                st.error("Please fill out all the fields.") 