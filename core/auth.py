import streamlit as st

def is_authenticated() -> bool:
    """
    Checks if a user is authenticated by verifying the presence of a token
    in the session state.
    """
    return 'token' in st.session_state 