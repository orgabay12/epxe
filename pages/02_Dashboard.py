import streamlit as st
import pandas as pd
import core.database as db
import datetime

st.set_page_config(layout="wide")

# --- Handle State Changes (Updates/Deletions) FIRST ---
# This is the most robust way to handle state in Streamlit.
# We process the results of the data_editor from the *previous* run at the top.
if "data_editor" in st.session_state and "df_for_editor" in st.session_state:
    editor_state = st.session_state.get("data_editor", {})
    df_from_last_run = st.session_state.get("df_for_editor", pd.DataFrame())

    # Handle Deletions
    if editor_state.get("deleted_rows") and not df_from_last_run.empty:
        ids_to_delete = [df_from_last_run.iloc[i]['id'] for i in editor_state["deleted_rows"]]
        for expense_id in ids_to_delete:
            db.delete_expense(int(expense_id))
        st.success(f"Deleted {len(ids_to_delete)} transaction(s).")
        # Clear the widget's state to prevent reprocessing and rerun
        del st.session_state["data_editor"]
        st.rerun()

    # Handle Edits
    if editor_state.get("edited_rows") and not df_from_last_run.empty:
        for row, changes in editor_state["edited_rows"].items():
            expense_id = df_from_last_run.iloc[row]['id']
            original_row = df_from_last_run.iloc[row].to_dict()
            updated_row = {**original_row, **changes}

            if isinstance(updated_row.get('date'), datetime.date):
                updated_row['date'] = updated_row['date'].strftime('%Y-%m-%d')
            
            db.update_expense(
                int(expense_id),
                updated_row['merchant'],
                float(updated_row['amount']),
                updated_row['date'],
                updated_row['category']
            )
        st.success("Transactions updated successfully.")
        # Clear the widget's state to prevent reprocessing and rerun
        del st.session_state["data_editor"]
        st.rerun()


st.title("Dashboard")

# Fetch data from the database
expenses = db.get_expenses()
categories_list = db.get_categories()
categories_dict = {cat['name']: {'id': cat['id'], 'budget': float(cat['budget'])} for cat in categories_list}

if expenses:
    transactions_df = pd.DataFrame(expenses)
    # Ensure correct data types for display
    transactions_df['amount'] = pd.to_numeric(transactions_df['amount'])
    transactions_df['date'] = pd.to_datetime(transactions_df['date'])
    
    # --- Determine Default Filters ---
    latest_year = None
    latest_month_num = 0
    if not transactions_df.empty:
        available_years_sorted = sorted(transactions_df['date'].dt.year.unique(), reverse=True)
        if available_years_sorted:
            latest_year = available_years_sorted[0]
            latest_month_num = transactions_df[transactions_df['date'].dt.year == latest_year]['date'].dt.month.max()

    col1, col2 = st.columns(2)

    with col1:
        # Get unique years from data, add "All Time"
        years = ["All Time"] + sorted(transactions_df['date'].dt.year.unique(), reverse=True)
        
        # Determine default index for year
        year_index = 0 # Default to "All Time"
        if latest_year in years:
            year_index = years.index(latest_year)
            
        selected_year = st.selectbox("Select Year", years, index=year_index)

    with col2:
        # Month selection
        months = ["All Time", "January", "February", "March", "April", "May", "June", 
                "July", "August", "September", "October", "November", "December"]
        
        # Determine default index for month
        month_index = int(latest_month_num) if latest_month_num > 0 else 0
        
        selected_month_name = st.selectbox("Select Month", months, index=month_index)

    # Filter DataFrame based on selection
    filtered_df = transactions_df.copy()
    if selected_year != "All Time":
        filtered_df = filtered_df[filtered_df['date'].dt.year == selected_year]
    
    if selected_month_name != "All Time":
        month_number = months.index(selected_month_name)
        filtered_df = filtered_df[filtered_df['date'].dt.month == month_number]

    # --- Visualizations (using filtered_df) ---
    st.header("Spending vs. Budget")
    spending_by_category = filtered_df.groupby('category')['amount'].sum()
    
    for category_name, cat_data in categories_dict.items():
        budget = cat_data['budget']
        spending = spending_by_category.get(category_name, 0)
        
        # Conditionally color if budget is exceeded
        if budget > 0 and spending > budget:
            st.markdown(
                f'<p style="color:red;"><b>{category_name}</b>: ₪{spending:,.2f} / ₪{budget:,.2f} (Over Budget)</p>',
                unsafe_allow_html=True
            )
            st.markdown(
                """<div style="background-color: red; height: 10px; width: 100%; border-radius: 5px;"></div>""",
                unsafe_allow_html=True
            )
        else:
            progress = min(spending / budget, 1.0) if budget > 0 else 0
            st.write(f"**{category_name}**: ₪{spending:,.2f} / ₪{budget:,.2f}")
            st.progress(progress)
        
        # Collapsible expander for category-specific transactions
        with st.expander(f"View Transactions for {category_name}"):
            category_transactions_df = filtered_df[filtered_df['category'] == category_name]
            if not category_transactions_df.empty:
                st.dataframe(category_transactions_df, use_container_width=True)
            else:
                st.write("No transactions for this category yet.")

    st.header("Edit or Delete Transactions")
    
    # The data_editor now uses num_rows="dynamic" for deletion.
    # Its state is stored for processing on the next run.
    # The on_change callback is crucial for saving the state of the dataframe
    # that was passed to the editor.
    st.data_editor(
        filtered_df,
        hide_index=True,
        num_rows="dynamic", # Allows deletion and addition
        column_config={
            "category": st.column_config.SelectboxColumn(
                "Category",
                options=list(categories_dict.keys()),
                required=True
            ),
            "date": st.column_config.DateColumn(
                "Date",
                format="YYYY-MM-DD"
            ),
            "id": None # Hide the ID column
        },
        key="data_editor",
        on_change=lambda: st.session_state.update(df_for_editor=filtered_df.copy())
    )

else:
    st.info("No transactions added yet. Add a transaction on the 'Upload' page to see your dashboard.") 