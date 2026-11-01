"""Streamlit Google OpenID Connect integration.

The app never implements passwords. Google is the identity provider and the
stable ``sub`` claim is the external identity key.
"""

import streamlit as st

from database.models import User
from services.user_service import get_or_create_user

USER_STATE_PREFIXES = ("auth_", "groq_chat_", "user_")
CLAIM_FIELDS = (
    "sub",
    "email",
    "name",
    "given_name",
    "family_name",
    "picture",
    "locale",
    "email_verified",
)
REQUIRED_AUTH_SETTINGS = (
    "redirect_uri",
    "cookie_secret",
    "client_id",
    "client_secret",
    "server_metadata_url",
)


def _claim(user, name):
    """Read a claim from st.user, which supports both key and attribute access."""
    try:
        return user[name]
    except (KeyError, TypeError, IndexError):
        return getattr(user, name, None)


def is_logged_in(user=None) -> bool:
    """Return True only when Streamlit reports a logged-in OIDC user."""
    try:
        user = st.user if user is None else user
        return bool(_claim(user, "is_logged_in"))
    except Exception:
        return False


def user_claims(user=None) -> dict | None:
    """Extract the claims we store, or None when the visitor is not signed in."""
    try:
        user = st.user if user is None else user
    except Exception:
        return None
    if not is_logged_in(user):
        return None

    claims = {}
    for field in CLAIM_FIELDS:
        value = _claim(user, field)
        if value is not None:
            claims[field] = value

    # A logged-in user without a stable subject cannot be linked to a row.
    if not claims.get("sub"):
        return None
    return claims


def auth_is_configured(secrets=None) -> bool:
    """Check that the [auth] secrets needed by st.login() are present."""
    if secrets is None:
        try:
            secrets = st.secrets
        except Exception:
            return False

    try:
        auth = secrets["auth"]
    except Exception:
        return False

    for key in REQUIRED_AUTH_SETTINGS:
        try:
            value = auth[key]
        except Exception:
            return False
        if not str(value or "").strip():
            return False
    return True


def clear_user_session_state(state) -> None:
    """Remove app-owned user data before another identity's widgets are rendered."""
    for key in list(state.keys()):
        if isinstance(key, str) and key.startswith(USER_STATE_PREFIXES):
            del state[key]


def user_session_key(user_id: int, name: str) -> str:
    """Return a Streamlit state key isolated to one authenticated account."""
    return f"user_{user_id}_{name}"


def logout() -> None:
    """Clear local session state, then let Streamlit remove the identity cookie."""
    clear_user_session_state(st.session_state)
    st.logout()


def resolve_authenticated_user(db, user=None, session_state=None) -> User | None:
    """Return the database user for the current OIDC session.

    The resolved user id is cached in the Streamlit session so a rerun does not
    write a login timestamp on every interaction. The cache is only trusted
    when the stored row still matches the current Google subject.
    """
    try:
        user = st.user if user is None else user
        state = st.session_state if session_state is None else session_state
    except Exception:
        return None

    claims = user_claims(user)
    if claims is None:
        return None

    cached_id = state.get("auth_user_id")
    if cached_id is not None:
        cached = db.get(User, cached_id)
        if cached is not None and cached.google_sub == claims["sub"]:
            return cached
        # A different Google identity now owns this browser session. Remove the
        # previous account's cached identity and chat history before continuing.
        clear_user_session_state(state)

    account = get_or_create_user(db, claims)
    state["auth_user_id"] = account.id
    state["auth_user"] = {
        "id": account.id,
        "email": account.email,
        "name": account.name or account.email,
        "picture_url": account.picture_url,
    }
    return account


def render_login_page() -> None:
    """Render the signed-out landing page."""
    st.title("💰 My Expense Tracker")
    st.caption("Personal finance · INR · Asia/Kolkata")
    st.subheader("Sign in")

    if not auth_is_configured():
        st.warning("Google sign-in is not configured yet.")
        st.markdown(
            "Add an `[auth]` section to `.streamlit/secrets.toml` (or to the "
            "Streamlit Cloud secrets manager). See `.streamlit/secrets.toml.example`."
        )
        with st.expander("Required configuration keys"):
            st.code(
                "[auth]\n"
                'redirect_uri = "http://localhost:8501/oauth2callback"\n'
                'cookie_secret = "<strong-random-string>"\n'
                'client_id = "<google-client-id>"\n'
                'client_secret = "<google-client-secret>"\n'
                'server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"',
                language="toml",
            )
        st.caption(
            "This app does not implement password login. Google handles authentication."
        )
        return

    st.button("Continue with Google", type="primary", on_click=st.login)
    st.caption(
        "Authentication is handled by Google. This app never receives or stores "
        "your Google password."
    )


def render_user_sidebar(account: dict) -> None:
    """Show the signed-in identity and the logout action in the sidebar."""
    with st.sidebar:
        st.markdown("---")
        picture = (account or {}).get("picture_url")
        if picture:
            st.image(picture, width=48)
        st.markdown(f"**{(account or {}).get('name') or 'Signed in'}**")
        if (account or {}).get("email"):
            st.caption(account["email"])
        st.button("Log out", key="logout_button", on_click=logout)
        st.caption("Your financial data is private to your account.")
