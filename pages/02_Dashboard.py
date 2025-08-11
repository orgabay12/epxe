import streamlit as st
import pandas as pd
import core.database as db
import datetime
from core.auth import is_authenticated
import calendar

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

# Custom CSS to change expander hover color
# This targets the expander header using a more stable attribute selector
st.markdown("""
<style>
    div[data-testid="stExpander"] summary:hover {
        color: #808080 !important; /* Grey color on hover */
    }
</style>
""", unsafe_allow_html=True)

# --- Authentication Check ---
if not is_authenticated():
    st.error("🔴 Please log in to view this page.")
    st.stop()

st.sidebar.write(f"Welcome, **{st.session_state.get('user_info', {}).get('name', '')}**!")
if st.sidebar.button("Logout", key="dashboard_logout"):
    st.session_state['action'] = 'logout'
    st.switch_page("Home.py")

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

# Fetch data from the database
expenses = db.get_expenses()
categories_list = db.get_categories()
categories_dict = {cat['name']: {'id': cat['id'], 'budget': float(cat['budget'])} for cat in categories_list}
total_budget = sum(c['budget'] for c in categories_dict.values()) if categories_dict else 0

if not expenses:
    st.title("📊 Dashboard")
    st.info("No transactions added yet. Add a transaction on the 'Upload' page to see your dashboard.")
    st.stop()

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

# --- Calculations for Title and Days Left ---
total_spending = filtered_df['amount'].sum()
days_left_str = ""

# Only calculate days left if a specific month and year are selected
if selected_year != "All Time" and selected_month_name != "All Time":
    today = datetime.date.today()
    selected_month_num = months.index(selected_month_name)

    # Past
    if selected_year < today.year or (selected_year == today.year and selected_month_num < today.month):
        days_left = 0
    # Present
    elif selected_year == today.year and selected_month_num == today.month:
        _, days_in_month = calendar.monthrange(selected_year, selected_month_num)
        days_left = days_in_month - today.day
    # Future
    else:
        _, days_left = calendar.monthrange(selected_year, selected_month_num)

    days_left_str = f"| {days_left} days left"


# --- Display Title ---
# Use columns for split alignment
left_title, right_title = st.columns(2)
with left_title:
    st.markdown(f'<h1 style="text-align: left;">₪{total_spending:,.2f} / ₪{total_budget:,.2f}</h1>', unsafe_allow_html=True)
with right_title:
    if days_left_str: # Only show if there are days to display
        st.markdown(f'<h1 style="text-align: right;">{days_left_str.replace("|", "").strip()}</h1>', unsafe_allow_html=True)

st.divider()


# Sort by date descending before displaying anywhere
if not filtered_df.empty:
    filtered_df = filtered_df.sort_values(by="date", ascending=False)
        
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
            st.dataframe(
                category_transactions_df[['merchant', 'amount', 'date']], 
                use_container_width=True,
                hide_index=True
            )
        else:
            st.write("No transactions for this category yet.")

st.header("Edit or Delete Transactions")
    
# The data_editor now uses num_rows="dynamic" for deletion.
# Its state is stored for processing on the next run.
# The on_change callback is crucial for saving the state of the dataframe
# that was passed to the editor.
st.data_editor(
    filtered_df,
    column_order=("merchant", "category", "date", "amount"),
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