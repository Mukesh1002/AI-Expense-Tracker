import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from agent.expense_tools import TOOL_DEFINITIONS, execute_tool
from agent.groq_client import (
    EMPTY_RESPONSE_MESSAGE,
    MAX_ROUNDS_MESSAGE,
    REQUEST_TIMEOUT_SECONDS,
    GroqRequestError,
    GroqResponseError,
    _get_client,
    get_model_name,
    run_groq_turn,
    sanitize_error_message,
)
from database.models import Expense, Income
from services.expense_service import add_expense
from services.income_service import add_income

# Used by tests that never reach a database-backed tool.
USER_ID = 1


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def assistant_response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def install_fake_client(monkeypatch, responses):
    completions = FakeCompletions(responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr("agent.groq_client._get_client", lambda: client)
    return completions


def tool_payload(request, index):
    tool_messages = [
        message for message in request["messages"] if message["role"] == "tool"
    ]
    return json.loads(tool_messages[index]["content"])


# --------------------------------------------------------------------------- #
# Client initialization and configuration
# --------------------------------------------------------------------------- #

def test_client_initialization_uses_key_timeout_and_no_internal_retries(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    captured = {}

    def fake_groq(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("agent.groq_client.Groq", fake_groq)
    _get_client()

    assert captured["api_key"] == "test-key-not-real"
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["max_retries"] == 0


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is missing"):
        _get_client()


def test_placeholder_api_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "your_groq_api_key")

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is missing"):
        _get_client()


def test_model_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")

    assert get_model_name() == "openai/gpt-oss-20b"


def test_default_model_is_gpt_oss_120b(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    assert get_model_name() == "openai/gpt-oss-120b"


def test_request_uses_configured_model_and_auto_tool_choice(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    completions = install_fake_client(monkeypatch, [assistant_response("Hello.")])

    answer, _ = run_groq_turn(None, [], "hello", user_id=USER_ID)

    assert answer == "Hello."
    request = completions.requests[0]
    assert request["model"] == "openai/gpt-oss-20b"
    assert request["tool_choice"] == "auto"
    assert request["tools"] == TOOL_DEFINITIONS
    assert request["messages"][0]["role"] == "system"


# --------------------------------------------------------------------------- #
# Tool definitions
# --------------------------------------------------------------------------- #

def test_tool_definitions_are_openai_compatible():
    names = [tool["function"]["name"] for tool in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))
    assert "delete_expense" not in names
    assert set(names) == {
        "list_expense_categories",
        "add_expense",
        "add_income",
        "get_expenses",
        "get_incomes",
        "get_monthly_summary",
        "get_category_summary",
        "update_expense",
        "update_income",
    }

    for tool in TOOL_DEFINITIONS:
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["description"]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        properties = parameters.get("properties", {})
        assert set(parameters.get("required", [])) <= set(properties)
        assert all("type" in spec for spec in properties.values())

    add_expense_tool = next(
        tool for tool in TOOL_DEFINITIONS
        if tool["function"]["name"] == "add_expense"
    )
    assert {"amount", "description", "category", "expense_date"} <= set(
        add_expense_tool["function"]["parameters"]["properties"]
    )


def test_no_ai_delete_tool_is_exposed(db_session, user):
    expense = add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date.today(),
        user_id=user.id,
    )

    with pytest.raises(ValueError, match="Unsupported tool"):
        execute_tool(
            db_session,
            "delete_expense",
            {"expense_id": expense.id},
            user_id=user.id,
        )

    assert db_session.get(Expense, expense.id) is not None


# --------------------------------------------------------------------------- #
# Tool-calling flow
# --------------------------------------------------------------------------- #

def test_function_call_flow_builds_correct_message_history(db_session, user, monkeypatch):
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_1",
                        "add_expense",
                        json.dumps(
                            {
                                "amount": 300,
                                "description": "Dinner",
                                "category": "Food",
                                "expense_date": date.today().isoformat(),
                                "payment_method": "UPI",
                            }
                        ),
                    )
                ],
            ),
            assistant_response("Dinner expense recorded."),
        ],
    )

    answer, history = run_groq_turn(
        db_session, [], "I spent 300 rupees on dinner today.", user_id=user.id
    )

    assert answer == "Dinner expense recorded."
    assert len(completions.requests) == 2

    second_messages = completions.requests[1]["messages"]
    assistant_message = next(
        message for message in second_messages if message["role"] == "assistant"
    )
    assert assistant_message["tool_calls"][0]["id"] == "call_1"
    assert assistant_message["tool_calls"][0]["type"] == "function"
    assert assistant_message["tool_calls"][0]["function"]["name"] == "add_expense"

    tool_message = next(
        message for message in second_messages if message["role"] == "tool"
    )
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["name"] == "add_expense"
    assert json.loads(tool_message["content"])["success"] is True

    expense = db_session.scalar(select(Expense))
    assert expense.amount_paise == 30000
    assert expense.source == "AI_CHAT"

    assert [message["role"] for message in history] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert history[-3]["tool_calls"][0]["id"] == "call_1"
    assert history[-2]["tool_call_id"] == "call_1"
    assert history[-1] == {
        "role": "assistant",
        "content": "Dinner expense recorded.",
    }


def test_multiple_tool_calls_in_one_response(db_session, user, monkeypatch):
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_expense",
                        "add_expense",
                        json.dumps(
                            {
                                "amount": 300,
                                "description": "Dinner",
                                "category": "Food",
                                "expense_date": date.today().isoformat(),
                            }
                        ),
                    ),
                    tool_call(
                        "call_income",
                        "add_income",
                        json.dumps(
                            {
                                "amount": 5000,
                                "source": "Salary",
                                "income_date": date.today().isoformat(),
                            }
                        ),
                    ),
                ],
            ),
            assistant_response("Recorded both."),
        ],
    )

    answer, _ = run_groq_turn(
        db_session, [], "Dinner 300 and salary 5000 today.", user_id=user.id
    )

    assert answer == "Recorded both."
    assert len(db_session.scalars(select(Expense)).all()) == 1
    assert len(db_session.scalars(select(Income)).all()) == 1

    tool_messages = [
        message
        for message in completions.requests[1]["messages"]
        if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "call_expense",
        "call_income",
    ]
    assert all(json.loads(message["content"])["success"] for message in tool_messages)


def test_invalid_json_arguments_are_reported_without_execution(db_session, user, monkeypatch):
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [tool_call("call_bad", "add_expense", "{not valid json")],
            ),
            assistant_response("I could not read that."),
        ],
    )

    answer, _ = run_groq_turn(db_session, [], "Add an expense.", user_id=user.id)

    assert answer == "I could not read that."
    assert db_session.scalars(select(Expense)).all() == []
    payload = tool_payload(completions.requests[1], 0)
    assert payload["success"] is False
    assert "Invalid JSON arguments" in payload["error"]


def test_unknown_function_is_reported_without_execution(db_session, user, monkeypatch):
    expense = add_expense(
        db_session,
        amount=100,
        description="Tea",
        category_name="Food",
        expense_date=date.today(),
        user_id=user.id,
    )
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [tool_call("call_x", "delete_expense", json.dumps({"expense_id": expense.id}))],
            ),
            assistant_response("Deletion is not available in chat."),
        ],
    )

    answer, _ = run_groq_turn(
        db_session, [], "Delete my tea expense.", user_id=user.id
    )

    assert answer == "Deletion is not available in chat."
    payload = tool_payload(completions.requests[1], 0)
    assert payload["success"] is False
    assert "Unsupported tool: delete_expense" in payload["error"]
    assert db_session.get(Expense, expense.id) is not None


def test_missing_required_arguments_are_reported(db_session, user, monkeypatch):
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_missing",
                        "add_expense",
                        json.dumps(
                            {
                                "amount": 300,
                                "description": "Dinner",
                                "expense_date": date.today().isoformat(),
                            }
                        ),
                    )
                ],
            ),
            assistant_response("Which category?"),
        ],
    )

    run_groq_turn(db_session, [], "I spent 300 on dinner.", user_id=user.id)

    payload = tool_payload(completions.requests[1], 0)
    assert payload["success"] is False
    assert "Missing required argument 'category'" in payload["error"]
    assert db_session.scalars(select(Expense)).all() == []


def test_invalid_argument_type_is_reported(db_session, user, monkeypatch):
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_type",
                        "add_expense",
                        json.dumps(
                            {
                                "amount": "three hundred",
                                "description": "Dinner",
                                "category": "Food",
                                "expense_date": date.today().isoformat(),
                            }
                        ),
                    )
                ],
            ),
            assistant_response("How much was it?"),
        ],
    )

    run_groq_turn(db_session, [], "I spent some money on dinner.", user_id=user.id)

    payload = tool_payload(completions.requests[1], 0)
    assert payload["success"] is False
    assert "must be a number" in payload["error"]
    assert db_session.scalars(select(Expense)).all() == []


def test_tool_execution_error_is_reported_and_session_stays_usable(
    db_session, user, monkeypatch
):
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_category",
                        "add_expense",
                        json.dumps(
                            {
                                "amount": 300,
                                "description": "Dinner",
                                "category": "Not A Category",
                                "expense_date": date.today().isoformat(),
                            }
                        ),
                    )
                ],
            ),
            assistant_response("That category does not exist."),
        ],
    )

    run_groq_turn(
        db_session, [], "Spend 300 on dinner in Not A Category.", user_id=user.id
    )

    payload = tool_payload(completions.requests[1], 0)
    assert payload["success"] is False
    assert "Unknown or inactive expense category" in payload["error"]
    assert execute_tool(
        db_session, "list_expense_categories", {}, user_id=user.id
    )["categories"]


def test_repeated_identical_tool_call_is_not_executed_twice(db_session, user, monkeypatch):
    args = json.dumps(
        {
            "amount": 300,
            "description": "Dinner",
            "category": "Food",
            "expense_date": date.today().isoformat(),
        }
    )
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call("call_first", "add_expense", args),
                    tool_call("call_repeat", "add_expense", args),
                ],
            ),
            assistant_response("Dinner recorded once."),
        ],
    )

    answer, _ = run_groq_turn(
        db_session, [], "I spent 300 on dinner.", user_id=user.id
    )

    assert answer == "Dinner recorded once."
    assert len(db_session.scalars(select(Expense)).all()) == 1

    second_payload = tool_payload(completions.requests[1], 1)
    assert second_payload["success"] is True
    assert "already executed in this turn" in second_payload["note"]


def test_maximum_tool_rounds_stops_the_loop(db_session, user, monkeypatch):
    monkeypatch.setattr("agent.groq_client.MAX_TOOL_ROUNDS", 3)
    args = json.dumps(
        {
            "amount": 300,
            "description": "Dinner",
            "category": "Food",
            "expense_date": date.today().isoformat(),
        }
    )
    completions = install_fake_client(
        monkeypatch,
        [
            assistant_response(None, [tool_call(f"call_{index}", "add_expense", args)])
            for index in range(3)
        ],
    )

    answer, history = run_groq_turn(
        db_session, [], "I spent 300 on dinner.", user_id=user.id
    )

    assert len(completions.requests) == 3
    assert answer == MAX_ROUNDS_MESSAGE
    assert history[-1] == {"role": "assistant", "content": MAX_ROUNDS_MESSAGE}
    assert len(db_session.scalars(select(Expense)).all()) == 1


# --------------------------------------------------------------------------- #
# Response and error handling
# --------------------------------------------------------------------------- #

def test_empty_model_response_is_handled(monkeypatch):
    install_fake_client(monkeypatch, [assistant_response(None, None)])

    answer, history = run_groq_turn(None, [], "hello", user_id=USER_ID)

    assert answer == EMPTY_RESPONSE_MESSAGE
    assert history[-1]["content"] == EMPTY_RESPONSE_MESSAGE


def test_response_without_choices_is_reported(monkeypatch):
    install_fake_client(monkeypatch, [SimpleNamespace(choices=[])])

    with pytest.raises(GroqResponseError, match="no response choices"):
        run_groq_turn(None, [], "hello", user_id=USER_ID)


def test_api_error_includes_status_without_exposing_key(monkeypatch):
    api_key = "gsk_" + "A1b2C3d4" * 6
    monkeypatch.setenv("GROQ_API_KEY", api_key)

    class FakeAuthError(Exception):
        status_code = 401

    completions = install_fake_client(
        monkeypatch, [FakeAuthError(f"Invalid API key: {api_key}")]
    )

    with pytest.raises(GroqRequestError) as error:
        run_groq_turn(None, [], "hello", user_id=USER_ID)

    message = str(error.value)
    assert "HTTP 401" in message
    assert api_key not in message
    assert "[REDACTED]" in message
    assert len(completions.requests) == 1


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    class FakeRateLimitError(Exception):
        status_code = 429

    monkeypatch.setattr("agent.groq_client.time.sleep", lambda seconds: None)
    completions = install_fake_client(
        monkeypatch,
        [FakeRateLimitError("rate limit exceeded"), assistant_response("Recovered.")],
    )

    answer, _ = run_groq_turn(None, [], "hello", user_id=USER_ID)

    assert answer == "Recovered."
    assert len(completions.requests) == 2


def test_timeout_after_retries_reports_request_error(monkeypatch):
    class FakeTimeoutError(Exception):
        status_code = 408

    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-120b")
    monkeypatch.setattr("agent.groq_client.time.sleep", lambda seconds: None)
    completions = install_fake_client(
        monkeypatch,
        [FakeTimeoutError("request timed out"), FakeTimeoutError("request timed out")],
    )

    with pytest.raises(GroqRequestError, match="timed out"):
        run_groq_turn(None, [], "hello", user_id=USER_ID)

    assert len(completions.requests) == 2


def test_transient_error_falls_back_to_alternate_model(monkeypatch):
    class FakeUnavailableError(Exception):
        status_code = 503

    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b")
    monkeypatch.setattr("agent.groq_client.MAX_REQUEST_ATTEMPTS", 1)
    completions = install_fake_client(
        monkeypatch,
        [FakeUnavailableError("model overloaded"), assistant_response("Fallback answered.")],
    )

    answer, _ = run_groq_turn(None, [], "hello", user_id=USER_ID)

    assert answer == "Fallback answered."
    assert [request["model"] for request in completions.requests] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]


def test_transient_error_reports_when_all_models_fail(monkeypatch):
    class FakeUnavailableError(Exception):
        status_code = 503

    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b")
    monkeypatch.setattr("agent.groq_client.MAX_REQUEST_ATTEMPTS", 1)
    install_fake_client(
        monkeypatch,
        [FakeUnavailableError("model overloaded"), FakeUnavailableError("still down")],
    )

    with pytest.raises(GroqRequestError, match="fallback models were also unavailable"):
        run_groq_turn(None, [], "hello", user_id=USER_ID)


def test_sanitize_error_message_redacts_secrets(monkeypatch):
    api_key = "gsk_" + "Z9y8X7w6" * 6
    monkeypatch.setenv("GROQ_API_KEY", api_key)

    text = sanitize_error_message(
        f"failed with {api_key}\napi_key=abcdef123 authorization: Bearer {api_key}"
    )

    assert api_key not in text
    assert "\n" not in text
    assert "[REDACTED]" in text
    assert len(text) <= 700


# --------------------------------------------------------------------------- #
# Updates and conversation history
# --------------------------------------------------------------------------- #

def test_update_expense_function_call_updates_existing_row(db_session, user, monkeypatch):
    expense = add_expense(
        db_session,
        amount=300,
        description="Dinner",
        category_name="Food",
        expense_date=date.today(),
        user_id=user.id,
        payment_method="UPI",
    )
    expense_id = expense.id
    install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_update",
                        "update_expense",
                        json.dumps(
                            {
                                "expense_id": expense_id,
                                "amount": 450,
                                "description": "Dinner",
                                "category": "Food",
                                "expense_date": date.today().isoformat(),
                                "payment_method": "UPI",
                            }
                        ),
                    )
                ],
            ),
            assistant_response("Dinner updated."),
        ],
    )

    answer, _ = run_groq_turn(
        db_session, [], "Update my dinner expense to 450 rupees.", user_id=user.id
    )

    updated = db_session.scalar(select(Expense))
    assert answer == "Dinner updated."
    assert updated.id == expense_id
    assert updated.amount_paise == 45000
    assert len(db_session.scalars(select(Expense)).all()) == 1


def test_update_income_function_call_updates_existing_row(db_session, user, monkeypatch):
    income = add_income(
        db_session,
        amount=5000,
        source="Salary",
        income_date=date.today(),
        user_id=user.id,
    )
    income_id = income.id
    install_fake_client(
        monkeypatch,
        [
            assistant_response(
                None,
                [
                    tool_call(
                        "call_income_update",
                        "update_income",
                        json.dumps(
                            {
                                "income_id": income_id,
                                "amount": 6000,
                                "source": "Salary",
                                "income_date": date.today().isoformat(),
                            }
                        ),
                    )
                ],
            ),
            assistant_response("Income updated."),
        ],
    )

    answer, _ = run_groq_turn(
        db_session, [], "Update my salary to 6000.", user_id=user.id
    )

    updated = db_session.scalar(select(Income))
    assert answer == "Income updated."
    assert updated.id == income_id
    assert updated.amount_paise == 600000
    assert len(db_session.scalars(select(Income)).all()) == 1


def test_history_is_reused_across_turns(monkeypatch):
    completions = install_fake_client(
        monkeypatch,
        [assistant_response("First answer."), assistant_response("Second answer.")],
    )

    _, history = run_groq_turn(None, [], "First question", user_id=USER_ID)
    answer, _ = run_groq_turn(None, history, "Second question", user_id=USER_ID)

    assert answer == "Second answer."
    second_request_messages = completions.requests[1]["messages"]
    assert [message["role"] for message in second_request_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert second_request_messages[1]["content"] == "First question"
    assert second_request_messages[2]["content"] == "First answer."
    assert second_request_messages[3]["content"] == "Second question"
