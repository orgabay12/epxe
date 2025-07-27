import streamlit as st
import core.database as db
from core.config import settings # Import the centralized settings

# --- Global Setup ---
st.set_page_config(
    page_title="Personal Finance Dashboard",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)
db.initialize_database()

# --- Main Page Content ---
st.title("Welcome to your Personal Finance Dashboard!")

st.markdown(
    """
    This application helps you track and manage your personal expenses.
    Use the navigation sidebar to get started.

    ### How to use this app:
    - **Upload**: Go to the Upload page to add new expenses. You can either upload a
      credit card statement image for automatic processing or enter transactions manually.
    - **Dashboard**: Visit the Dashboard page to see a visual breakdown of your
      spending compared to your budgets.
    - **Settings**: On the Settings page, you can customize your spending categories
      and set your monthly budgets.
    """
) 