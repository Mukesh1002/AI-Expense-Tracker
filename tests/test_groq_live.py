"""Optional live Groq check. Never runs as part of the default test suite.

Usage (PowerShell):
    $env:RUN_GROQ_LIVE_TESTS = "1"
    python -m pytest tests/test_groq_live.py -q
"""

import os

import pytest
from sqlalchemy import select

import utils.config  # noqa: F401  (loads .env before reading GROQ_API_KEY)
from database.models import Expense

API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
RUN_LIVE = os.getenv("RUN_GROQ_LIVE_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not RUN_LIVE or not API_KEY or API_KEY.lower() == "your_groq_api_key",
    reason="Set RUN_GROQ_LIVE_TESTS=1 and GROQ_API_KEY to run the live Groq test.",
)


def test_live_groq_function_calling_round_trip(db_session):
    from agent.groq_client import get_model_name, run_groq_turn

    answer, history = run_groq_turn(
        db_session,
        [],
        "I spent 321 rupees on a live-test dinner today. "
        "Use the Food category and UPI as the payment method.",
    )

    assert isinstance(answer, str) and answer.strip()
    assert history[0] == {
        "role": "user",
        "content": (
            "I spent 321 rupees on a live-test dinner today. "
            "Use the Food category and UPI as the payment method."
        ),
    }

    expenses = db_session.scalars(select(Expense)).all()
    assert len(expenses) == 1, f"expected exactly one tool-created expense, got {len(expenses)}"
    assert expenses[0].amount_paise == 32100
    assert expenses[0].category.name == "Food"
    assert expenses[0].source == "AI_CHAT"
    assert get_model_name()


def test_live_groq_read_only_turn(db_session):
    from agent.groq_client import run_groq_turn

    answer, _ = run_groq_turn(
        db_session,
        [],
        "Show my expenses for October 2026.",
    )

    assert isinstance(answer, str) and answer.strip()
    assert db_session.scalars(select(Expense)).all() == []
