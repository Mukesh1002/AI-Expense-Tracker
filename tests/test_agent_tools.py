from datetime import date

import pytest

from agent.expense_tools import execute_tool
from database.models import Expense
from services.expense_service import add_expense


def test_list_expense_categories(db_session, user):
    result = execute_tool(db_session, "list_expense_categories", {}, user_id=user.id)
    assert "Food" in result["categories"]


def test_add_expense_tool(db_session, user):
    result = execute_tool(
        db_session,
        "add_expense",
        {
            "amount": 125.50,
            "description": "Lunch",
            "category": "Food",
            "expense_date": "2026-11-01",
            "payment_method": "UPI",
        },
        user_id=user.id,
    )
    assert result["success"] is True
    assert result["amount"] == "125.50"


def test_monthly_summary_tool(db_session, user):
    add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        user_id=user.id,
    )
    result = execute_tool(
        db_session,
        "get_monthly_summary",
        {"month": 11, "year": 2026},
        user_id=user.id,
    )
    assert result["total_expenses"] == "100.00"
    assert result["expense_count"] == 1


def test_tools_only_see_the_signed_in_users_data(db_session, user, other_user):
    add_expense(
        db_session,
        amount=100,
        description="Mine",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        user_id=user.id,
    )
    add_expense(
        db_session,
        amount=900,
        description="Theirs",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        user_id=other_user.id,
    )

    mine = execute_tool(
        db_session, "get_expenses", {}, user_id=user.id
    )
    theirs = execute_tool(
        db_session, "get_expenses", {}, user_id=other_user.id
    )
    summary = execute_tool(
        db_session,
        "get_monthly_summary",
        {"month": 11, "year": 2026},
        user_id=user.id,
    )

    assert [row["description"] for row in mine["expenses"]] == ["Mine"]
    assert [row["description"] for row in theirs["expenses"]] == ["Theirs"]
    assert summary["total_expenses"] == "100.00"
    assert summary["expense_count"] == 1


def test_ai_cannot_update_another_users_expense(db_session, user, other_user):
    expense = add_expense(
        db_session,
        amount=100,
        description="Mine",
        category_name="Food",
        expense_date=date(2026, 11, 1),
        user_id=user.id,
    )

    with pytest.raises(ValueError, match="Expense not found"):
        execute_tool(
            db_session,
            "update_expense",
            {
                "expense_id": expense.id,
                "amount": 200,
                "description": "Hijacked",
                "category": "Food",
                "expense_date": "2026-11-01",
            },
            user_id=other_user.id,
        )

    assert db_session.get(Expense, expense.id).description == "Mine"
