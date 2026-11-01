from datetime import date

import pytest
from sqlalchemy import select

from database.models import Expense, Income
from services.expense_service import (
    add_expense,
    delete_expense,
    list_expenses,
    update_expense,
)
from services.income_service import add_income, list_incomes, update_income
from utils.money import paise_to_rupees, rupees_to_paise


def test_money_conversion():
    assert rupees_to_paise("125.50") == 12550
    assert str(paise_to_rupees(12550)) == "125.50"


def test_reject_zero_or_negative_amount():
    with pytest.raises(ValueError):
        rupees_to_paise("0")
    with pytest.raises(ValueError):
        rupees_to_paise("-10")


def test_add_and_list_expense(db_session, user):
    expense = add_expense(
        db_session,
        amount="450.50",
        description="Dinner",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        user_id=user.id,
        payment_method="UPI",
    )
    assert expense.amount_paise == 45050
    assert expense.category.name == "Food"
    assert expense.user_id == user.id
    assert len(list_expenses(db_session, user_id=user.id)) == 1


def test_unknown_category_is_rejected(db_session, user):
    with pytest.raises(ValueError):
        add_expense(
            db_session,
            amount=100,
            description="Test",
            category_name="Not a category",
            expense_date=date.today(),
            user_id=user.id,
        )


def test_delete_expense(db_session, user):
    expense = add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date.today(),
        user_id=user.id,
    )
    assert delete_expense(db_session, expense.id, user_id=user.id) is True
    assert db_session.get(Expense, expense.id) is None
    assert delete_expense(db_session, 9999, user_id=user.id) is False


def test_add_income(db_session, user):
    income = add_income(
        db_session,
        amount="50000",
        source="Salary",
        income_date=date(2026, 11, 1),
        user_id=user.id,
    )
    assert income.amount_paise == 5000000
    assert income.user_id == user.id
    assert db_session.scalar(select(Income).where(Income.id == income.id)) is not None


def test_update_expense(db_session, user):
    expense = add_expense(
        db_session, amount="100", description="Snack",
        category_name="Food", expense_date=date.today(),
        user_id=user.id,
    )
    updated = update_expense(
        db_session, expense.id, user_id=user.id, amount="250.75",
        description="Groceries", category_name="Groceries",
        expense_date=date(2026, 11, 1), payment_method="UPI",
    )
    assert updated.amount_paise == 25075
    assert updated.description == "Groceries"
    assert updated.category.name == "Groceries"


def test_update_income(db_session, user):
    income = add_income(
        db_session, amount="1000", source="Other",
        income_date=date.today(), user_id=user.id,
    )
    updated = update_income(
        db_session, income.id, user_id=user.id, amount="2000",
        source="Freelance", income_date=date(2026, 11, 1),
    )
    assert updated.amount_paise == 200000
    assert updated.source == "Freelance"


def test_expenses_are_isolated_between_users(db_session, user, other_user):
    add_expense(
        db_session, amount=100, description="Mine", category_name="Food",
        expense_date=date(2026, 11, 1), user_id=user.id,
    )
    add_expense(
        db_session, amount=200, description="Theirs", category_name="Food",
        expense_date=date(2026, 11, 1), user_id=other_user.id,
    )

    assert [item.description for item in list_expenses(db_session, user_id=user.id)] == [
        "Mine"
    ]
    assert [
        item.description for item in list_expenses(db_session, user_id=other_user.id)
    ] == ["Theirs"]


def test_income_is_isolated_between_users(db_session, user, other_user):
    add_income(
        db_session, amount=1000, source="Mine", income_date=date(2026, 11, 1),
        user_id=user.id,
    )
    add_income(
        db_session, amount=2000, source="Theirs", income_date=date(2026, 11, 1),
        user_id=other_user.id,
    )

    assert [item.source for item in list_incomes(db_session, user_id=user.id)] == [
        "Mine"
    ]
    assert [
        item.source for item in list_incomes(db_session, user_id=other_user.id)
    ] == ["Theirs"]


def test_update_and_delete_cannot_cross_users(db_session, user, other_user):
    expense = add_expense(
        db_session, amount=100, description="Mine", category_name="Food",
        expense_date=date.today(), user_id=user.id,
    )

    with pytest.raises(ValueError, match="Expense not found"):
        update_expense(
            db_session, expense.id, user_id=other_user.id, amount=200,
            description="Hijacked", category_name="Food", expense_date=date.today(),
        )

    assert delete_expense(db_session, expense.id, user_id=other_user.id) is False
    assert db_session.get(Expense, expense.id) is not None


def test_income_update_cannot_cross_users(db_session, user, other_user):
    income = add_income(
        db_session, amount=1000, source="Mine", income_date=date.today(),
        user_id=user.id,
    )

    with pytest.raises(ValueError, match="Income record not found"):
        update_income(
            db_session, income.id, user_id=other_user.id, amount=2000,
            source="Hijacked", income_date=date.today(),
        )


def test_writes_require_an_existing_user(db_session):
    with pytest.raises(ValueError, match="user_id"):
        add_expense(
            db_session, amount=100, description="No owner", category_name="Food",
            expense_date=date.today(), user_id=9999,
        )

    with pytest.raises(ValueError, match="user_id"):
        add_income(
            db_session, amount=100, source="No owner", income_date=date.today(),
            user_id=9999,
        )


def test_unowned_rows_are_rejected_by_the_database(db_session):
    expense = Expense(
        amount_paise=100,
        description="No owner",
        category_id=1,
        expense_date=date.today(),
    )
    db_session.add(expense)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()
