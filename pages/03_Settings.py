import streamlit as st
import core.database as db
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

st.title("Settings: Categories & Budgets")

# Fetch categories from the database
categories_list = db.get_categories()

# Calculate and display total expected expenses
if categories_list:
    total_budget = sum(float(c['budget']) for c in categories_list)
    st.metric(label="Total Expected Expenses", value=f"₪{total_budget:,.2f}")
    st.divider()

st.header("Manage Your Budgets")

# Display each category with a number input to update its budget
for cat in categories_list:
    new_budget = st.number_input(
        f"{cat['name']}",
        value=float(cat['budget']),
        key=f"budget_{cat['id']}",
        min_value=0.0,
        step=50.0
    )
    if new_budget != float(cat['budget']):
        db.update_category_budget(cat['id'], new_budget)
        st.success(f"Updated budget for {cat['name']}!")
        st.rerun()

st.header("Add New Category")
with st.form("new_category_form", clear_on_submit=True):
    new_category_name = st.text_input("Category Name")
    new_category_budget = st.number_input("Budget (₪)", min_value=0.0, step=50.0)
    submitted = st.form_submit_button("Add Category")
    if submitted and new_category_name:
        db.add_category(new_category_name, new_category_budget)
        st.success(f"Added new category: {new_category_name}")
        st.rerun() 