import streamlit as st
from streamlit_oauth import OAuth2Component
from core.config import settings
import base64
import json
from streamlit_local_storage import LocalStorage
from datetime import datetime, timezone
from core.database import initialize_database
import os, sys, subprocess, pathlib, logging

logger = logging.getLogger("playwright_setup")

if os.getenv("PLAYWRIGHT_AUTO_INSTALL")=="True":
    _marker = pathlib.Path("/tmp/.pw_installed")
    if not _marker.exists():
        try:
            logger.info("Playwright auto-install enabled. Installing Chromium ...")
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if result.returncode != 0:
                logger.error("Playwright Chromium install failed with code %s", result.returncode)
                logger.error("Playwright output:\n%s", (result.stdout or "").strip())
                raise RuntimeError("Playwright Chromium install failed")
            _marker.touch()
            logger.info("Playwright Chromium install completed.")
        except Exception:
            logger.exception("Playwright Chromium install failed")
    else:
        logger.info("Playwright install skipped (marker present).")

# Ensure DB is initialized (runs once per process)
initialize_database()

# --- App Configuration & Helper Functions ---
st.set_page_config(page_title="Home", page_icon="🏠", layout="wide")
localS = LocalStorage()

def decode_id_token(token):
    """
    Safely decodes a Google ID token and checks for expiration.
    Returns the user payload if the token is valid, otherwise None.
    """
    try:
        payload_b64 = token.split('.')[1]
        payload_bytes = base64.b64decode(payload_b64 + '==')
        user_info = json.loads(payload_bytes)

        # Check if the token is expired.
        if 'exp' in user_info and datetime.fromtimestamp(user_info['exp'], tz=timezone.utc) < datetime.now(tz=timezone.utc):
            return None  # Token is expired

        return user_info
    except Exception:
        return None

# --- Action Handler for State Changes ---
# This runs first to handle pending actions from the previous run.
if 'action' in st.session_state:
    action = st.session_state.pop('action')
    if action == 'login':
        token_data = st.session_state.pop('token_data')
        localS.setItem('token', token_data)
        st.session_state['token'] = token_data
        st.session_state['user_info'] = decode_id_token(token_data.get('id_token', '')) or {}
    elif action == 'logout':
        # Clear token from browser storage and session
        try:
            localS.deleteAll()
        except Exception:
            # Fallback if component not ready
            localS.setItem('token', None)
        st.session_state.clear()


# --- OAuth Configuration ---
AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

oauth2 = OAuth2Component(
    settings.GCP_OAUTH_CLIENT_ID,
    settings.GCP_OAUTH_CLIENT_SECRET,
    AUTHORIZE_ENDPOINT,
    TOKEN_ENDPOINT,
    TOKEN_ENDPOINT, # Refresh token endpoint
    REVOKE_ENDPOINT
)

# --- Authentication Logic ---
# Try to load token from session state first, then from local storage
token = st.session_state.get('token')
if not token:
    token_candidate = localS.getItem('token')
    # Normalize: require a dict with an 'id_token'
    if isinstance(token_candidate, dict) and token_candidate.get('id_token'):
        st.session_state['token'] = token_candidate
        token = token_candidate
    else:
        token = None

# Main logic based on token presence
if not token:
    st.title("Welcome to Your Personal Finance Dashboard!")
    st.write("Please log in to continue.")

    result = oauth2.authorize_button(
        name="Continue with Google",
        icon="https://www.google.com/favicon.ico",
        redirect_uri=settings.APP_URL,
        scope="openid email profile",
        key="google",
        extras_params={"prompt": "consent", "access_type": "offline"},
        use_container_width=True
    )
    if result:
        token_data = result.get('token')
        if token_data:
            id_token = token_data.get('id_token')
            user_info = decode_id_token(id_token)
            if user_info:
                user_email = user_info.get('email')
                authorized_users_list = [email.strip() for email in settings.AUTHORIZED_USERS.split(',')]
                if user_email in authorized_users_list:
                    # Set up the action for the next run
                    st.session_state['action'] = 'login'
                    st.session_state['token_data'] = token_data
                    st.rerun()
                else:
                    st.error("Access denied. Your email is not authorized.")
            else:
                st.error("Could not retrieve user information from Google.")
        else:
            st.error("Login failed. No token received.")

else:
    id_token = token.get('id_token')
    user_info = decode_id_token(id_token)

    if user_info:
        st.session_state['user_info'] = user_info
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
            st.session_state['action'] = 'logout'
            st.rerun()
    else:
        # If the token is invalid (expired or corrupted), force a logout.
        st.session_state['action'] = 'logout'
        st.rerun() 