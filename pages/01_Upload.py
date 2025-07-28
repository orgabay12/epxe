import streamlit as st
import datetime
import os
import core.database as db
from agent import run_agent
from core.auth import is_authenticated

# --- Authentication Check ---
if not is_authenticated():
    st.warning("Please log in to access this page.")
    st.stop()

# --- Sidebar ---
st.sidebar.title("Navigation")
if st.sidebar.button("Logout"):
    del st.session_state.token
    st.rerun()

st.title("Upload Transactions")

# --- State Management (for non-persistent UI state) ---
if 'processed_file_id' not in st.session_state:
    st.session_state.processed_file_id = None

# Fetch categories from the database for use in the app
categories_list = db.get_categories()
categories_dict = {cat['name']: {'id': cat['id'], 'budget': float(cat['budget'])} for cat in categories_list}

# --- AI-Powered Transaction Entry ---
st.header("Add Transaction via Receipt")

uploaded_file = st.file_uploader("Upload a receipt image", type=["jpg", "jpeg", "png"])

# Reset the processed file ID if the uploader is cleared by the user
if uploaded_file is None:
    st.session_state.processed_file_id = None

# Process the file only if it's a new, unprocessed file
if uploaded_file is not None and uploaded_file.file_id != st.session_state.get('processed_file_id'):
    image_bytes = uploaded_file.getvalue()
    
    with st.spinner("AI is processing your receipt..."):
        categorized_transactions = run_agent(
            image_bytes=image_bytes,
            categories=list(categories_dict.keys())
        )
        
        added_count = 0
        skipped_count = 0
        if categorized_transactions:
            for tx in categorized_transactions:
                # Check for duplicates before adding
                if not db.transaction_exists(tx.merchant, tx.amount, tx.date):
                    db.add_expense(tx.merchant, tx.amount, tx.date, tx.category)
                    added_count += 1
                else:
                    print(f"Skipping duplicate transaction: {tx.merchant}, {tx.amount}, {tx.date}")
                    skipped_count += 1

        if added_count > 0:
            st.success(f"Successfully added {added_count} new transaction(s).")


# --- Manual Transaction Entry ---
st.header("Add a New Transaction")

with st.form("transaction_form", clear_on_submit=True):
    merchant = st.text_input("Merchant")
    amount = st.number_input("Amount (₪)", min_value=0.0, format="%.2f")
    date = st.date_input("Date", value=datetime.date.today())

    category_options = list(categories_dict.keys())
    category = st.selectbox("Category", options=category_options, index=category_options.index('Uncategorized'))

    add_transaction_submitted = st.form_submit_button("Add Transaction")
    if add_transaction_submitted:
        if merchant and amount > 0:
            # Check for duplicates before adding
            if not db.transaction_exists(merchant, amount, date.strftime("%Y-%m-%d")):
                db.add_expense(merchant, amount, date.strftime("%Y-%m-%d"), category)
                st.success("Transaction added!")
                # We can optionally rerun to clear the form, but clear_on_submit=True already handles it
            else:
                st.warning("This transaction already exists.")
        else:
            st.error("Please fill out all the fields.") 