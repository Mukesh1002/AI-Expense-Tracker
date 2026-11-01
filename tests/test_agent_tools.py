from datetime import date

import pytest

from agent.expense_tools import execute_tool
from database.models import Expense
from services.expense_service import add_expense


def test_list_expense_categories(db_session):
    result = execute_tool(db_session, "list_expense_categories", {})
    assert "Food" in result["categories"]


def test_add_expense_tool(db_session):
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
    )
    assert result["success"] is True
    assert result["amount"] == "125.50"


def test_monthly_summary_tool(db_session):
    add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date(2026, 11, 1),
    )
    result = execute_tool(
        db_session,
        "get_monthly_summary",
        {"month": 11, "year": 2026},
    )
    assert result["total_expenses"] == "100.00"
    assert result["expense_count"] == 1


def test_tools_retrieve_all_single_user_transactions(db_session):
    add_expense(
        db_session,
        amount=100,
        description="Dinner",
        category_name="Food",
        expense_date=date(2026, 11, 1),
    )
    result = execute_tool(db_session, "get_expenses", {})
    summary = execute_tool(
        db_session,
        "get_monthly_summary",
        {"month": 11, "year": 2026},
    )

    assert [row["description"] for row in result["expenses"]] == ["Dinner"]
    assert summary["total_expenses"] == "100.00"
    assert summary["expense_count"] == 1


def test_ai_cannot_delete_transactions(db_session):
    expense = add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date.today(),
    )

    with pytest.raises(ValueError, match="Unsupported tool"):
        execute_tool(db_session, "delete_expense", {"expense_id": expense.id})

    assert db_session.get(Expense, expense.id) is not None
