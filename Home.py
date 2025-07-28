import streamlit as st
import asyncio
from streamlit_oauth import OAuth2Component
from core.config import settings
import base64
import json

def decode_id_token(token):
    """Safely decodes a Google ID token to get user information."""
    try:
        # The ID token is the second part of the JWT
        payload = token.split('.')[1]
        # It needs to be base64 decoded with padding
        decoded_payload = base64.b64decode(payload + '==').decode('utf-8')
        return json.loads(decoded_payload)
    except Exception as e:
        print(f"Error decoding ID token: {e}")
        return None

# --- App Configuration ---
st.set_page_config(page_title="Home", page_icon="🏠", layout="wide")

# --- OAuth Configuration ---
AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REFRESH_TOKEN_URL = "https://oauth2.googleapis.com/token" # Same as token endpoint for Google
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

# --- Main App ---
st.title("Welcome to Your Personal Finance Dashboard!")
st.write("Please log in to continue.")

# Create an OAuth2Component instance
oauth2 = OAuth2Component(
    settings.GCP_OAUTH_CLIENT_ID, 
    settings.GCP_OAUTH_CLIENT_SECRET, 
    AUTHORIZE_ENDPOINT, 
    TOKEN_ENDPOINT, 
    REFRESH_TOKEN_URL, 
    REVOKE_ENDPOINT
)

# Check if a token exists in the session state
if 'token' not in st.session_state:
    # If not, show the login button
    result = oauth2.authorize_button(
        name="Continue with Google",
        icon="https://www.google.com/favicon.ico",
        redirect_uri="http://localhost:8501",
        scope="openid email profile",
        key="google",
        extras_params={"prompt": "consent", "access_type": "offline"},
        use_container_width=True
    )
    if result:
        # User has successfully authenticated.
        # Now, we need to check if they are on our allowlist.
        token_data = result.get('token')
        if token_data:
            id_token = token_data.get('id_token')
            user_info = decode_id_token(id_token)

            if user_info:
                user_email = user_info.get('email')
                authorized_users_list = [email.strip() for email in settings.AUTHORIZED_USERS.split(',')]
                if user_email in authorized_users_list:
                    # If authorized, store the token and rerun.
                    st.session_state.token = token_data # Store the full token data
                    st.rerun()
                else:
                    # If not authorized, show an error.
                    st.error("Access denied. Your email is not authorized.")
            else:
                st.error("Could not retrieve user information from Google.")
        else:
            st.error("Login failed. No token received.")

else:
    # If a token exists, show the user's info and a logout button
    token_data = st.session_state['token']
    id_token = token_data.get('id_token')
    user_info = decode_id_token(id_token)
    
    if user_info:
        st.sidebar.write(f"Welcome, **{user_info.get('name')}**!")
        
        st.title("Welcome to Your Personal Finance Dashboard!")
        st.markdown(
            """
            **👈 Select a page from the sidebar to get started:**

            - **Upload:** Add new transactions.
            - **Dashboard:** Visualize your spending.
            - **Settings:** Manage your categories and budgets.
            """
        )
        
        if st.sidebar.button("Logout"):
            del st.session_state.token
            st.rerun()

# The logic to protect other pages will go here, checking st.session_state.token 