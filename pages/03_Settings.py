import streamlit as st
import core.database as db

st.set_page_config(layout="wide")

st.title("Settings: Categories & Budgets")

st.header("Manage Your Budgets")

# Fetch categories from the database
categories_list = db.get_categories()

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