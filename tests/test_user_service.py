from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from database.models import AgentConversation, Expense, Income, User
from services.expense_service import add_expense
from services.income_service import add_income
from services.user_service import (
    claims_to_profile,
    get_or_create_user,
    get_user_by_google_sub,
)

CLAIMS = {
    "sub": "google-sub-123",
    "email": "asha@example.com",
    "email_verified": True,
    "name": "Asha Rao",
    "given_name": "Asha",
    "family_name": "Rao",
    "picture": "https://example.com/asha.png",
    "locale": "en-IN",
}


def test_claims_to_profile_maps_google_claims():
    profile = claims_to_profile(CLAIMS)

    assert profile["google_sub"] == "google-sub-123"
    assert profile["email"] == "asha@example.com"
    assert profile["name"] == "Asha Rao"
    assert profile["given_name"] == "Asha"
    assert profile["family_name"] == "Rao"
    assert profile["picture_url"] == "https://example.com/asha.png"
    assert profile["locale"] == "en-IN"
    assert profile["email_verified"] is True


def test_claims_require_stable_subject_identifier():
    with pytest.raises(ValueError, match="subject identifier"):
        claims_to_profile({"email": "asha@example.com"})

    with pytest.raises(ValueError, match="subject identifier"):
        claims_to_profile({"sub": "   ", "email": "asha@example.com"})


def test_claims_require_email():
    with pytest.raises(ValueError, match="email address"):
        claims_to_profile({"sub": "google-sub-123"})


def test_get_or_create_user_creates_user_with_timestamps(db_session):
    user = get_or_create_user(db_session, CLAIMS)

    assert user.id is not None
    assert user.google_sub == "google-sub-123"
    assert user.email == "asha@example.com"
    assert user.name == "Asha Rao"
    assert user.email_verified is True
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.last_login_at is not None


def test_get_or_create_user_is_idempotent_for_same_sub(db_session):
    first = get_or_create_user(db_session, CLAIMS)
    second = get_or_create_user(db_session, CLAIMS)

    assert first.id == second.id
    assert db_session.scalar(select(func.count(User.id))) == 1


def test_duplicate_google_identity_is_rejected_by_database(db_session):
    get_or_create_user(db_session, CLAIMS)

    db_session.add(
        User(google_sub="google-sub-123", email="other@example.com", email_verified=True)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.scalar(select(func.count(User.id))) == 1


def test_profile_fields_are_refreshed_on_next_login(db_session):
    user = get_or_create_user(db_session, CLAIMS)
    changed = {
        **CLAIMS,
        "name": "Asha R. Rao",
        "picture": "https://example.com/asha-new.png",
    }

    refreshed = get_or_create_user(db_session, changed)

    assert refreshed.id == user.id
    assert refreshed.name == "Asha R. Rao"
    assert refreshed.picture_url == "https://example.com/asha-new.png"
    assert db_session.scalar(select(func.count(User.id))) == 1


def test_get_user_by_google_sub_returns_none_for_unknown(db_session):
    assert get_user_by_google_sub(db_session, "missing") is None


def test_user_owns_expenses_income_and_conversations(db_session):
    user = get_or_create_user(db_session, CLAIMS)

    expense = add_expense(
        db_session,
        amount=300,
        description="Dinner",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        user_id=user.id,
    )
    income = add_income(
        db_session,
        amount=5000,
        source="Salary",
        income_date=date(2026, 11, 1),
        user_id=user.id,
    )
    conversation = AgentConversation(
        session_id="session-1",
        role="user",
        message="I spent 300 on dinner.",
        user_id=user.id,
    )
    db_session.add(conversation)
    db_session.commit()
    db_session.refresh(expense)
    db_session.refresh(income)

    assert expense.user is not None
    assert expense.user.id == user.id
    assert income.user.id == user.id
    assert conversation.user.id == user.id
    assert {item.id for item in user.expenses} == {expense.id}
    assert {item.id for item in user.income} == {income.id}


def test_new_financial_rows_require_a_known_user(db_session):
    """After the clean start, an unowned transaction cannot be created."""
    with pytest.raises(ValueError, match="user_id"):
        add_expense(
            db_session,
            amount=100,
            description="Unowned tea",
            category_name="Food",
            expense_date=date(2026, 11, 1),
            user_id=9999,
        )

    assert db_session.scalar(select(func.count(Expense.id))) == 0


def test_services_accept_user_id_without_changing_business_logic(db_session):
    user = get_or_create_user(db_session, CLAIMS)
    income = add_income(
        db_session,
        amount=2500,
        source="Freelance",
        income_date=date(2026, 11, 1),
        user_id=user.id,
    )

    assert income.user_id == user.id
    assert income.amount_paise == 250000
    assert db_session.scalar(select(func.count(Income.id))) == 1
