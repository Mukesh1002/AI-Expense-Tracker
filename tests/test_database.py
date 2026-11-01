from datetime import date

import pytest
from sqlalchemy import inspect, select

from database.models import Expense, Income
from services.expense_service import (
    add_expense,
    delete_expense,
    list_expenses,
    update_expense,
)
from services.income_service import (
    add_income,
    delete_income,
    list_incomes,
    update_income,
)
from utils.money import paise_to_rupees, rupees_to_paise


def test_money_conversion():
    assert rupees_to_paise("125.50") == 12550
    assert str(paise_to_rupees(12550)) == "125.50"


def test_reject_zero_or_negative_amount():
    with pytest.raises(ValueError):
        rupees_to_paise("0")
    with pytest.raises(ValueError):
        rupees_to_paise("-10")


def test_single_user_schema_has_no_auth_ownership(db_session):
    tables = set(inspect(db_session.bind).get_table_names())
    assert "users" not in tables
    for table in ("expenses", "income", "agent_conversations"):
        assert "user_id" not in {
            column["name"] for column in inspect(db_session.bind).get_columns(table)
        }


def test_add_and_list_expense(db_session):
    expense = add_expense(
        db_session,
        amount="450.50",
        description="Dinner",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        payment_method="UPI",
    )
    assert expense.amount_paise == 45050
    assert expense.category.name == "Food"
    assert len(list_expenses(db_session)) == 1


def test_unknown_category_is_rejected(db_session):
    with pytest.raises(ValueError):
        add_expense(
            db_session,
            amount=100,
            description="Test",
            category_name="Not a category",
            expense_date=date.today(),
        )


def test_delete_expense(db_session):
    expense = add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date.today(),
    )
    assert delete_expense(db_session, expense.id) is True
    assert db_session.get(Expense, expense.id) is None
    assert delete_expense(db_session, 9999) is False


def test_add_income(db_session):
    income = add_income(
        db_session,
        amount="50000",
        source="Salary",
        income_date=date(2026, 11, 1),
    )
    assert income.amount_paise == 5000000
    assert db_session.scalar(select(Income).where(Income.id == income.id)) is not None


def test_update_expense(db_session):
    expense = add_expense(
        db_session,
        amount="100",
        description="Snack",
        category_name="Food",
        expense_date=date.today(),
    )
    transaction_id = expense.id
    creation_time = expense.created_at
    updated = update_expense(
        db_session,
        transaction_id,
        amount="250.75",
        description="Groceries",
        category_name="Groceries",
        expense_date=date(2026, 11, 1),
        payment_method="UPI",
    )
    assert updated.id == transaction_id
    assert updated.created_at == creation_time
    assert updated.amount_paise == 25075
    assert updated.description == "Groceries"
    assert updated.category.name == "Groceries"


def test_update_income(db_session):
    income = add_income(
        db_session, amount="1000", source="Other", income_date=date.today()
    )
    transaction_id = income.id
    creation_time = income.created_at
    updated = update_income(
        db_session,
        transaction_id,
        amount="2000",
        source="Freelance",
        income_date=date(2026, 11, 1),
    )
    assert updated.id == transaction_id
    assert updated.created_at == creation_time
    assert updated.amount_paise == 200000
    assert updated.source == "Freelance"


@pytest.mark.parametrize("service", [add_expense, add_income])
@pytest.mark.parametrize("amount", ["0", "-1"])
def test_services_reject_nonpositive_amount(db_session, service, amount):
    kwargs = (
        {
            "amount": amount,
            "description": "Test",
            "category_name": "Food",
            "expense_date": date.today(),
        }
        if service is add_expense
        else {"amount": amount, "source": "Salary", "income_date": date.today()}
    )
    with pytest.raises(ValueError):
        service(db_session, **kwargs)


@pytest.mark.parametrize(
    ("service", "kwargs"),
    [
        (
            add_expense,
            {
                "amount": 100,
                "description": " ",
                "category_name": "Food",
                "expense_date": date.today(),
            },
        ),
        (
            add_income,
            {"amount": 100, "source": " ", "income_date": date.today()},
        ),
    ],
)
def test_services_reject_empty_required_text(db_session, service, kwargs):
    with pytest.raises(ValueError):
        service(db_session, **kwargs)


def test_delete_income(db_session):
    income = add_income(
        db_session,
        amount=1000,
        source="Salary",
        income_date=date.today(),
    )
    assert delete_income(db_session, income.id) is True
    assert db_session.get(Income, income.id) is None
    assert delete_income(db_session, 9999) is False


def test_list_income_and_expenses_apply_date_filters(db_session):
    add_expense(
        db_session,
        amount=100,
        description="Old expense",
        category_name="Food",
        expense_date=date(2026, 1, 1),
    )
    add_expense(
        db_session,
        amount=200,
        description="New expense",
        category_name="Food",
        expense_date=date(2026, 2, 1),
    )
    add_income(
        db_session,
        amount=1000,
        source="Old income",
        income_date=date(2026, 1, 1),
    )
    add_income(
        db_session,
        amount=2000,
        source="New income",
        income_date=date(2026, 2, 1),
    )

    assert [row.description for row in list_expenses(
        db_session, start_date=date(2026, 2, 1)
    )] == ["New expense"]
    assert [row.source for row in list_incomes(
        db_session, start_date=date(2026, 2, 1)
    )] == ["New income"]
