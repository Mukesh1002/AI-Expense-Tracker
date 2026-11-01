from types import SimpleNamespace

from sqlalchemy import func, select

from auth.streamlit_auth import (
    auth_is_configured,
    clear_user_session_state,
    is_logged_in,
    logout,
    resolve_authenticated_user,
    user_session_key,
    user_claims,
)
from database.models import User
from services.user_service import get_user_by_google_sub


def fake_user(**overrides):
    values = {
        "is_logged_in": True,
        "sub": "google-sub-123",
        "email": "asha@example.com",
        "email_verified": True,
        "name": "Asha Rao",
        "given_name": "Asha",
        "family_name": "Rao",
        "picture": "https://example.com/asha.png",
        "locale": "en-IN",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_logged_in_state_is_detected():
    assert is_logged_in(fake_user()) is True
    assert is_logged_in(fake_user(is_logged_in=False)) is False


def test_missing_login_state_is_treated_as_signed_out():
    assert is_logged_in(SimpleNamespace()) is False


def test_user_claims_extract_google_identity():
    claims = user_claims(fake_user())

    assert claims == {
        "sub": "google-sub-123",
        "email": "asha@example.com",
        "email_verified": True,
        "name": "Asha Rao",
        "given_name": "Asha",
        "family_name": "Rao",
        "picture": "https://example.com/asha.png",
        "locale": "en-IN",
    }


def test_user_claims_are_none_when_signed_out():
    assert user_claims(fake_user(is_logged_in=False)) is None


def test_user_claims_require_stable_subject():
    assert user_claims(fake_user(sub=None)) is None


def test_auth_configuration_requires_all_settings():
    complete = {
        "auth": {
            "redirect_uri": "http://localhost:8501/oauth2callback",
            "cookie_secret": "secret",
            "client_id": "client",
            "client_secret": "client-secret",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        }
    }
    assert auth_is_configured(complete) is True

    for key in complete["auth"]:
        incomplete = {"auth": {k: v for k, v in complete["auth"].items() if k != key}}
        assert auth_is_configured(incomplete) is False

    assert auth_is_configured({}) is False


def test_unauthenticated_visitor_does_not_create_a_user(db_session):
    state = {}

    account = resolve_authenticated_user(
        db_session, user=fake_user(is_logged_in=False), session_state=state
    )

    assert account is None
    assert state == {}
    assert db_session.scalar(select(func.count(User.id))) == 0


def test_authenticated_visitor_is_created_and_cached(db_session):
    state = {}

    account = resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )

    assert account is not None
    assert account.google_sub == "google-sub-123"
    assert state["auth_user_id"] == account.id
    assert state["auth_user"] == {
        "id": account.id,
        "email": "asha@example.com",
        "name": "Asha Rao",
        "picture_url": "https://example.com/asha.png",
    }
    assert db_session.scalar(select(func.count(User.id))) == 1

    again = resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )
    assert again.id == account.id
    assert db_session.scalar(select(func.count(User.id))) == 1


def test_stale_cached_identity_is_replaced(db_session):
    first = resolve_authenticated_user(
        db_session, user=fake_user(), session_state={}
    )
    state = {
        "auth_user_id": first.id,
        "auth_user": {"id": first.id},
        f"groq_chat_{first.id}_messages": [{"role": "user", "content": "private"}],
        f"groq_chat_{first.id}_history": [{"role": "user", "content": "private"}],
        f"user_{first.id}_page": "Add Expense",
        f"user_{first.id}_add_expense_amount": 300,
        f"user_{first.id}_add_expense_description": "private expense",
        f"user_{first.id}_add_expense_category": "Food",
        f"user_{first.id}_add_expense_payment": "UPI",
        f"user_{first.id}_add_expense_date": "2026-11-01",
        f"user_{first.id}_add_expense_notes": "private notes",
        f"user_{first.id}_add_income_amount": 5000,
        f"user_{first.id}_add_income_source": "private income",
        f"user_{first.id}_add_income_date": "2026-11-01",
        f"user_{first.id}_add_income_notes": "private income notes",
        f"user_{first.id}_edit_expense_select": "private expense selection",
        f"user_{first.id}_edit_expense_amount": 450,
        f"user_{first.id}_edit_expense_description": "private edited expense",
        f"user_{first.id}_edit_expense_category": "Food",
        f"user_{first.id}_edit_expense_payment": "Cash",
        f"user_{first.id}_edit_expense_date": "2026-11-02",
        f"user_{first.id}_edit_expense_notes": "private edit notes",
        f"user_{first.id}_edit_income_select": "private income selection",
        f"user_{first.id}_edit_income_amount": 6000,
        f"user_{first.id}_edit_income_source": "private edited source",
        f"user_{first.id}_edit_income_date": "2026-11-03",
        f"user_{first.id}_edit_income_notes": "private income edit notes",
        f"user_{first.id}_confirm_delete_expense": True,
        f"user_{first.id}_dashboard_month": "private filter",
        f"user_{first.id}_groq_chat_prompt": "private chat prompt",
    }

    second = resolve_authenticated_user(
        db_session,
        user=fake_user(sub="google-sub-999", email="other@example.com", name="Other"),
        session_state=state,
    )

    assert second.id != first.id
    assert state["auth_user_id"] == second.id
    assert state["auth_user"]["email"] == "other@example.com"
    assert not any(key.startswith("groq_chat_") for key in state)
    assert not any(key.startswith("user_") for key in state)
    assert db_session.scalar(select(func.count(User.id))) == 2


def test_clear_user_session_state_removes_all_user_data_only():
    state = {
        "auth_user_id": 1,
        "auth_user": {"id": 1},
        "groq_chat_messages": [{"role": "user"}],
        "groq_chat_history": [],
        "user_1_add_expense_description": "Dinner",
        "user_1_add_income_source": "Salary",
        "user_1_edit_expense_select": "expense 3",
        "user_1_edit_income_select": "income 2",
        "user_1_groq_chat_prompt": "private prompt",
        "app_configuration": 42,
        "_streamlit_oidc_state": "preserve until st.logout",
    }

    clear_user_session_state(state)

    assert state == {
        "app_configuration": 42,
        "_streamlit_oidc_state": "preserve until st.logout",
    }


def test_widget_state_keys_are_scoped_to_authenticated_user():
    assert user_session_key(1, "add_expense_description") == "user_1_add_expense_description"
    assert user_session_key(1, "add_expense_description") != user_session_key(
        2, "add_expense_description"
    )


def test_logout_then_account_switch_cannot_reuse_user_a_state(db_session, monkeypatch):
    state = {}
    first = resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )
    state.update({
        f"user_{first.id}_page": "Add Expense",
        f"user_{first.id}_add_expense_amount": 300,
        f"user_{first.id}_add_expense_description": "private dinner",
        f"user_{first.id}_add_expense_category": "Food",
        f"user_{first.id}_add_expense_date": "2026-11-01",
        f"user_{first.id}_add_expense_payment": "UPI",
        f"user_{first.id}_add_expense_notes": "private expense notes",
        f"user_{first.id}_add_income_amount": 5000,
        f"user_{first.id}_add_income_source": "private salary",
        f"user_{first.id}_add_income_date": "2026-11-01",
        f"user_{first.id}_add_income_notes": "private income notes",
        f"user_{first.id}_edit_expense_select": "expense 1",
        f"user_{first.id}_edit_expense_amount": 450,
        f"user_{first.id}_edit_expense_description": "private edited dinner",
        f"user_{first.id}_edit_income_select": "income 1",
        f"user_{first.id}_edit_income_amount": 6000,
        f"user_{first.id}_edit_income_source": "private edited salary",
        f"user_{first.id}_dashboard_month": "November",
        f"user_{first.id}_groq_chat_prompt": "private prompt",
        f"groq_chat_{first.id}_messages": [{"role": "user", "content": "private chat"}],
        f"groq_chat_{first.id}_history": [{"role": "user", "content": "private chat"}],
        "streamlit_internal_auth": "leave for st.logout",
        "app_configuration": "keep",
    })
    logout_snapshots = []
    fake_st = SimpleNamespace(
        session_state=state,
        logout=lambda: logout_snapshots.append(dict(state)),
    )
    monkeypatch.setattr("auth.streamlit_auth.st", fake_st)

    logout()

    assert logout_snapshots == [{
        "streamlit_internal_auth": "leave for st.logout",
        "app_configuration": "keep",
    }]
    second = resolve_authenticated_user(
        db_session,
        user=fake_user(sub="google-sub-999", email="other@example.com"),
        session_state=state,
    )

    assert second is not None
    assert second.id != first.id
    assert "private dinner" not in state.values()
    assert "private salary" not in state.values()
    assert "private chat" not in state.values()
    assert not any(key.startswith(f"user_{first.id}_") for key in state)
    assert not any(key.startswith("groq_chat_") for key in state)


def test_same_user_rerun_preserves_form_state(db_session):
    state = {}
    first = resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )
    description_key = f"user_{first.id}_add_expense_description"
    state[description_key] = "unsaved lunch"

    again = resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )

    assert again.id == first.id
    assert state[description_key] == "unsaved lunch"


def test_same_user_rerun_preserves_groq_chat_state(db_session):
    state = {}
    account = resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )
    messages_key = f"groq_chat_{account.id}_messages"
    history_key = f"groq_chat_{account.id}_history"
    state[messages_key] = [{"role": "assistant", "content": "private answer"}]
    state[history_key] = [{"role": "model", "parts": []}]

    resolve_authenticated_user(
        db_session, user=fake_user(), session_state=state
    )

    assert state[messages_key][0]["content"] == "private answer"
    assert state[history_key][0]["role"] == "model"


def test_logout_clears_state_and_calls_streamlit_logout(monkeypatch):
    calls = []
    logout_state = []
    state = {
        "auth_user_id": 1,
        "groq_chat_messages": [{"role": "user"}],
        "user_1_add_expense_description": "private",
        "user_1_page": "Add Expense",
        "streamlit_internal_auth": "preserve until logout",
        "app_configuration": "keep",
    }
    fake_st = SimpleNamespace(
        session_state=state,
        logout=lambda: (calls.append("logout"), logout_state.append(dict(state))),
    )
    monkeypatch.setattr("auth.streamlit_auth.st", fake_st)

    logout()

    assert calls == ["logout"]
    assert logout_state == [{
        "streamlit_internal_auth": "preserve until logout",
        "app_configuration": "keep",
    }]
    assert fake_st.session_state == logout_state[0]


def test_resolved_user_is_retrievable_by_google_sub(db_session):
    account = resolve_authenticated_user(
        db_session, user=fake_user(), session_state={}
    )

    stored = get_user_by_google_sub(db_session, "google-sub-123")
    assert stored is not None
    assert stored.id == account.id
